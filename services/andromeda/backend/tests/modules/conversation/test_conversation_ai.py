from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from andromeda.modules.conversation.contracts.language import (
    AssistantClarificationRequest,
    AssistantEntityCandidate,
    AssistantEntityMention,
    AssistantQueryInterpretation,
)
from andromeda.modules.conversation.contracts.public import (
    AdmissionUniversityScope,
    ConversationIntent,
    ConversationSlot,
    NextAction,
    ParsedQuery,
    PolicyQueryContext,
    PolicyQueryFocus,
    PolicyQueryYear,
    ProgramDiscoveryContext,
    QuerySession,
)
from andromeda.modules.conversation.domain.session import add_bounded_catalog_selection
from andromeda.modules.conversation.services.ai_interpretation import (
    clarification_is_grounded,
    merge_ai_interpretation,
)
from andromeda.modules.conversation.services.assistant import (
    AssistantService,
    _apply_contextual_follow_up,
)
from andromeda.modules.conversation.services.rule_parser import (
    RuleBasedQueryParser,
    remove_entity_name_metrics,
)
from andromeda.modules.disciplines.contracts.public import DisciplineAreaCode
from andromeda.modules.entity_resolution.contracts.public import (
    ResolutionEntityType,
    ResolutionStatus,
)
from andromeda.modules.proftest.contracts.public import ProfileScope
from andromeda.modules.programs.contracts.public import Program

NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
OWNER = ProfileScope(session_key_hash="a" * 64)


def test_ai_interpretation_keeps_only_entity_phrases_present_in_user_text() -> None:
    text = "Сравни бизнес-информатику"
    parsed = ParsedQuery(intent=ConversationIntent.UNKNOWN)
    interpretation = AssistantQueryInterpretation(
        intent=ConversationIntent.COMPARE_PROGRAMS,
        entities=(
            AssistantEntityMention(
                entity_type=ResolutionEntityType.PROGRAM,
                query="бизнес-информатику",
            ),
            AssistantEntityMention(
                entity_type=ResolutionEntityType.PROGRAM,
                query="Московский государственный университет",
            ),
        ),
    )

    merged = merge_ai_interpretation(
        parsed,
        interpretation,
        text=text,
        allowed_metrics=("business_share",),
        current_intent=None,
        missing_slots=(),
    )

    assert merged.intent is ConversationIntent.COMPARE_PROGRAMS
    assert merged.program_queries == ("бизнес-информатику",)
    assert merged.metric_codes == ()


def test_ai_does_not_override_a_deterministically_recognized_intent() -> None:
    text = "Сравни программы по математике"
    parsed = RuleBasedQueryParser().parse(text)
    interpretation = AssistantQueryInterpretation(
        intent=ConversationIntent.ANALYTICS_QUERY,
        metric_codes=("math_share",),
    )

    merged = merge_ai_interpretation(
        parsed,
        interpretation,
        text=text,
        allowed_metrics=("math_share",),
        current_intent=None,
        missing_slots=(),
    )

    assert merged.intent is ConversationIntent.COMPARE_PROGRAMS


def test_ai_preserves_the_active_intent_while_answering_a_clarification() -> None:
    interpretation = AssistantQueryInterpretation(
        intent=ConversationIntent.ANALYTICS_QUERY,
        entities=(
            AssistantEntityMention(
                entity_type=ResolutionEntityType.PROGRAM,
                query="бизнес-информатика",
            ),
        ),
    )

    merged = merge_ai_interpretation(
        ParsedQuery(),
        interpretation,
        text="бизнес-информатика",
        allowed_metrics=(),
        current_intent=ConversationIntent.COMPARE_PROGRAMS,
        missing_slots=(ConversationSlot.ENTITY,),
    )

    assert merged.intent is ConversationIntent.COMPARE_PROGRAMS
    assert merged.program_queries == ("бизнес-информатика",)


def test_ai_inflected_university_candidate_replaces_unresolvable_parser_alias() -> None:
    text = "Что есть по ИИ в Бауманке?"
    parsed = RuleBasedQueryParser().parse(text)
    interpretation = AssistantQueryInterpretation(
        intent=ConversationIntent.PROGRAM_DISCOVERY,
        entities=(
            AssistantEntityMention(
                entity_type=ResolutionEntityType.UNIVERSITY,
                query="Бауманке",
            ),
        ),
    )

    merged = merge_ai_interpretation(
        parsed,
        interpretation,
        text=text,
        allowed_metrics=(),
        current_intent=None,
        missing_slots=(),
    )

    assert merged.university_queries == ("Бауманке",)


def test_discovery_area_mention_is_not_treated_as_a_direction_entity() -> None:
    text = "Хотя нет, лучше сначала покажи программы по разработке"
    parsed = RuleBasedQueryParser().parse(text)
    merged = merge_ai_interpretation(
        parsed,
        AssistantQueryInterpretation(
            intent=ConversationIntent.PROGRAM_DISCOVERY,
            entities=(
                AssistantEntityMention(
                    entity_type=ResolutionEntityType.DIRECTION,
                    query="разработке",
                ),
            ),
        ),
        text=text,
        allowed_metrics=(),
        current_intent=ConversationIntent.COMPARE_PROGRAMS,
        missing_slots=(ConversationSlot.ENTITY,),
    )

    assert merged.intent is ConversationIntent.PROGRAM_DISCOVERY
    assert merged.direction_queries == ()
    assert merged.preferred_areas


def test_explicit_new_intent_overrides_active_clarification_intent() -> None:
    merged = merge_ai_interpretation(
        ParsedQuery(),
        AssistantQueryInterpretation(
            intent=ConversationIntent.COMPARE_PROGRAMS,
            starts_new_task=True,
        ),
        text="Хотя нет, сравни ИУ5 и ИУ7",
        allowed_metrics=(),
        current_intent=ConversationIntent.PROGRAM_DISCOVERY,
        missing_slots=(ConversationSlot.INTERESTS,),
    )

    assert merged.intent is ConversationIntent.COMPARE_PROGRAMS


def test_explicit_task_change_uses_ai_intent_when_parser_misclassifies_it() -> None:
    text = "Хотя нет, лучше сначала покажи программы по разработке"
    parsed = RuleBasedQueryParser().parse(text)
    merged = merge_ai_interpretation(
        parsed,
        AssistantQueryInterpretation(
            intent=ConversationIntent.PROGRAM_DISCOVERY,
            starts_new_task=True,
        ),
        text=text,
        allowed_metrics=(),
        current_intent=ConversationIntent.COMPARE_PROGRAMS,
        missing_slots=(ConversationSlot.ENTITY,),
    )

    assert merged.intent is ConversationIntent.PROGRAM_DISCOVERY


def test_unknown_ai_intent_preserves_active_intent_for_short_clarification() -> None:
    merged = merge_ai_interpretation(
        ParsedQuery(),
        AssistantQueryInterpretation(intent=ConversationIntent.UNKNOWN),
        text="ИИ",
        allowed_metrics=(),
        current_intent=ConversationIntent.PROGRAM_DISCOVERY,
        missing_slots=(ConversationSlot.INTERESTS,),
    )

    assert merged.intent is ConversationIntent.PROGRAM_DISCOVERY


def test_discovery_context_keeps_university_filter_follow_up_in_catalog_flow() -> None:
    session = QuerySession(
        session_id="query-session:" + "c" * 32,
        owner_scope=OWNER,
        intent=ConversationIntent.PROGRAM_DISCOVERY,
        program_discovery_context=ProgramDiscoveryContext(
            candidate_program_ids=(
                "program:bmstu:09.03.01-02",
                "program:bmstu:09.03.01-12",
            )
        ),
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    parsed = RuleBasedQueryParser().parse("А что из этого есть в Бауманке?")

    followed_up = _apply_contextual_follow_up(
        parsed, session, "А что из этого есть в Бауманке?"
    )

    assert followed_up.intent is ConversationIntent.PROGRAM_DISCOVERY
    assert followed_up.university_queries
    assert followed_up.program_queries == session.program_discovery_context.candidate_program_ids


def test_admission_inputs_do_not_get_captured_by_discovery_context() -> None:
    session = QuerySession(
        session_id="query-session:" + "d" * 32,
        owner_scope=OWNER,
        intent=ConversationIntent.PROGRAM_DISCOVERY,
        program_discovery_context=ProgramDiscoveryContext(
            candidate_program_ids=("program:bmstu:09.03.01-02",)
        ),
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    text = "А куда я пройду с 270 баллами в Бауманке?"
    parsed = RuleBasedQueryParser().parse(text)

    followed_up = _apply_contextual_follow_up(parsed, session, text)

    assert followed_up.intent is ConversationIntent.ADMISSION_SEARCH
    assert followed_up.program_queries == ()


def test_comparison_criterion_follow_up_keeps_the_compared_programs() -> None:
    program_ids = (
        "program:bmstu:09.03.01-02",
        "program:bmstu:09.03.01-12",
    )
    session = QuerySession(
        session_id="query-session:" + "e" * 32,
        owner_scope=OWNER,
        intent=ConversationIntent.COMPARE_PROGRAMS,
        entities={ResolutionEntityType.PROGRAM: program_ids},
        program_discovery_context=ProgramDiscoveryContext(),
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    text = "Какая из них больше про разработку, а какая про аналитику?"
    parsed = RuleBasedQueryParser().parse(text)

    followed_up = _apply_contextual_follow_up(parsed, session, text)

    assert followed_up.intent is ConversationIntent.COMPARE_PROGRAMS
    assert followed_up.program_queries == program_ids
    assert followed_up.metric_codes == ("programming_share", "analytics_share")
    assert followed_up.replace_metrics is True


def test_ai_metrics_are_bounded_to_registry_codes_and_zero_score_is_preserved() -> None:
    text = "Сравни направления, математика, мой балл 0"
    interpretation = AssistantQueryInterpretation(
        intent=ConversationIntent.COMPARE_PROGRAMS,
        metric_codes=("math_share", "not_a_metric"),
        total_score=Decimal(0),
    )

    merged = merge_ai_interpretation(
        ParsedQuery(),
        interpretation,
        text=text,
        allowed_metrics=("math_share",),
        current_intent=None,
        missing_slots=(),
    )

    assert merged.metric_codes == ("math_share",)
    assert merged.total_score == Decimal(0)


def test_ai_accepts_explicit_scope_wording_used_by_applicant() -> None:
    merged = merge_ai_interpretation(
        ParsedQuery(),
        AssistantQueryInterpretation(
            intent=ConversationIntent.ADMISSION_SEARCH,
            admission_university_scope=AdmissionUniversityScope.ANY_UNIVERSITY,
        ),
        text="Ищи по любым вузам",
        allowed_metrics=(),
        current_intent=None,
        missing_slots=(),
    )

    assert merged.admission_university_scope is AdmissionUniversityScope.ANY_UNIVERSITY


def test_ai_does_not_turn_a_metric_phrase_into_a_program_entity() -> None:
    text = "Сравни программы по математике"
    parsed = RuleBasedQueryParser().parse(text)
    interpretation = AssistantQueryInterpretation(
        intent=ConversationIntent.COMPARE_PROGRAMS,
        entities=(
            AssistantEntityMention(
                entity_type=ResolutionEntityType.PROGRAM,
                query="по математике",
            ),
        ),
    )

    merged = merge_ai_interpretation(
        parsed,
        interpretation,
        text=text,
        allowed_metrics=("math_share",),
        current_intent=None,
        missing_slots=(),
    )

    assert merged.program_queries == ()
    assert merged.metric_codes == ("math_share",)


def test_ai_does_not_turn_inflected_metric_into_a_program_entity() -> None:
    text = "Какие дисциплины ты отнёс к программированию?"
    parsed = RuleBasedQueryParser().parse(text)
    interpretation = AssistantQueryInterpretation(
        intent=ConversationIntent.PROGRAM_DETAILS,
        entities=(
            AssistantEntityMention(
                entity_type=ResolutionEntityType.PROGRAM,
                query="программированию",
            ),
        ),
    )

    merged = merge_ai_interpretation(
        parsed,
        interpretation,
        text=text,
        allowed_metrics=("programming_share",),
        current_intent=ConversationIntent.ANALYTICS_QUERY,
        missing_slots=(),
    )

    assert merged.program_queries == ()
    assert merged.metric_codes == ("programming_share",)


def test_ai_does_not_turn_comparison_criteria_into_catalog_entities() -> None:
    text = "Какая из них больше про разработку, а какая про аналитику?"
    parsed = RuleBasedQueryParser().parse(text)
    interpretation = AssistantQueryInterpretation(
        intent=ConversationIntent.COMPARE_PROGRAMS,
        entities=(
            AssistantEntityMention(
                entity_type=ResolutionEntityType.PROGRAM,
                query="про разработку",
            ),
            AssistantEntityMention(
                entity_type=ResolutionEntityType.DIRECTION,
                query="про аналитику",
            ),
        ),
    )

    merged = merge_ai_interpretation(
        parsed,
        interpretation,
        text=text,
        allowed_metrics=("programming_share", "analytics_share"),
        current_intent=ConversationIntent.COMPARE_PROGRAMS,
        missing_slots=(),
    )

    assert merged.program_queries == ()
    assert merged.direction_queries == ()
    assert merged.metric_codes == ("programming_share", "analytics_share")


def test_metric_words_inside_resolved_program_names_are_not_comparison_metrics() -> None:
    first = "Интеллектуальные системы обработки информации и управления"
    second = "Искусственный интеллект в системах обработки информации и управления"
    text = f"{first} и {second} по математике"

    assert remove_entity_name_metrics(
        text,
        ("ai_share", "math_share"),
        (first, second),
    ) == ("math_share",)


def test_ai_clarification_cannot_introduce_unprovided_numbers() -> None:
    request = AssistantClarificationRequest(
        user_message="Сравни эти программы",
        intent=ConversationIntent.COMPARE_PROGRAMS,
        missing_slots=(ConversationSlot.ENTITY,),
        current_question="Какие программы сравнить?",
    )

    assert clarification_is_grounded("Какие программы 2028 года сравнить?", request) is False
    assert clarification_is_grounded("Какие программы вы хотите сравнить?", request)
    assert clarification_is_grounded("А сравнить программы в МГУ?", request) is False


def test_ai_clarification_allows_normal_sentence_starts_but_not_new_names() -> None:
    request = AssistantClarificationRequest(
        user_message="Сравни две программы по математике",
        intent=ConversationIntent.COMPARE_PROGRAMS,
        missing_slots=(ConversationSlot.ENTITY,),
        current_question="Какие направления или программы сравнить?",
    )

    assert clarification_is_grounded(
        "Какие две программы по математике сравнить? "
        "Напишите их названия, можно своими словами.",
        request,
    )
    assert clarification_is_grounded(
        "Какие две программы по математике сравнить? "
        "Напишите, например, программу МГУ.",
        request,
    ) is False


class _ProgramReader:
    def __init__(self, programs: tuple[Program, ...]) -> None:
        self._programs = programs

    def get(self, program_id: str) -> Program | None:
        return next((item for item in self._programs if item.id == program_id), None)

    def list(self, university_id: str | None = None) -> tuple[Program, ...]:
        if university_id is None:
            return self._programs
        return tuple(
            item for item in self._programs
            if item.direction_id.startswith(f"direction:{university_id.removeprefix('university:')}:")
        )


def _program(direction_code: str, suffix: str, name: str) -> Program:
    code = f"{direction_code}-{suffix}"
    direction_id = f"direction:bmstu:{direction_code}"
    return Program(
        id=f"program:bmstu:{code}",
        direction_id=direction_id,
        code=code,
        name=name,
        education_year=2026,
        study_plan_url="https://example.edu/plan.pdf",
        source_url="https://example.edu/program",
    )


class _CandidateSelectingAI:
    def __init__(self, selected_id: str) -> None:
        self.selected_id = selected_id
        self.candidates: tuple[AssistantEntityCandidate, ...] = ()

    def select_catalog_candidate(
        self,
        _user_message: str,
        *,
        candidates: tuple[AssistantEntityCandidate, ...],
        rate_limit_key: str,
    ) -> str:
        assert rate_limit_key == "owner"
        self.candidates = candidates
        return self.selected_id


def test_ai_catalog_selection_is_limited_to_real_same_university_entries() -> None:
    programs = (
        _program("09.03.01", "02", "Информатика и вычислительная техника"),
        _program("09.03.02", "01", "Информационные системы и технологии"),
        Program(
            id="program:hse:09.03.02-01",
            direction_id="direction:hse:09.03.02",
            code="09.03.02-01",
            name="Другая программа другого вуза",
            education_year=2026,
            study_plan_url="https://hse.example.edu/plan.pdf",
            source_url="https://hse.example.edu/program",
        ),
    )
    selected_id = "direction:bmstu:09.03.02"
    ai = _CandidateSelectingAI(selected_id)
    service = object.__new__(AssistantService)
    service._programs = _ProgramReader(programs)
    service._conversation_ai = ai
    session = QuerySession(
        session_id="query-session:" + "b" * 32,
        owner_scope=OWNER,
        intent=ConversationIntent.COMPARE_PROGRAMS,
        entities={
            ResolutionEntityType.DIRECTION: ("direction:bmstu:09.03.01",),
        },
        missing_slots=(ConversationSlot.ENTITY,),
        next_action=NextAction.ASK_FOR_ENTITY,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    updated, unavailable, options = service._select_other_direction(
        session,
        "сравни с любым другим направлением",
        rate_limit_key="owner",
    )

    assert not unavailable
    assert options == ()
    assert updated.entities[ResolutionEntityType.DIRECTION] == (
        "direction:bmstu:09.03.01",
        selected_id,
    )
    assert len(ai.candidates) == 1
    assert ai.candidates[0].canonical_id == selected_id
    assert updated.frame.resolution_evidence["assistant_catalog_selection"].startswith(
        "strategy=bounded_ai_candidate;user_authorized=true;candidate_hash="
    )


def test_comparison_follow_up_uses_typed_ai_entities_before_splitting_long_names() -> None:
    first_name = "Интеллектуальные системы обработки информации и управления"
    second_name = "Искусственный интеллект в системах обработки информации и управления"
    ids = {
        first_name: "program:bmstu:09.03.01-02",
        second_name: "program:bmstu:09.03.01-12",
    }

    class ExactNameResolver:
        def resolve(self, entity_type, query, *, context=None, limit=10):  # type: ignore[no-untyped-def]
            canonical_id = ids.get(query) if entity_type is ResolutionEntityType.PROGRAM else None
            return SimpleNamespace(
                resolution_strategy="deterministic",
                status=ResolutionStatus.RESOLVED if canonical_id else ResolutionStatus.NOT_FOUND,
                selected_id=canonical_id,
            )

    service = object.__new__(AssistantService)
    service._entity_resolver = ExactNameResolver()
    session = QuerySession(
        session_id="query-session:" + "d" * 32,
        owner_scope=OWNER,
        intent=ConversationIntent.COMPARE_PROGRAMS,
        entities={ResolutionEntityType.UNIVERSITY: ("university:bmstu",)},
        metrics=("math_share",),
        missing_slots=(ConversationSlot.ENTITY,),
        next_action=NextAction.ASK_FOR_ENTITY,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    text = f"{first_name} и {second_name} в МГТУ имени Баумана"
    parsed = ParsedQuery(
        intent=ConversationIntent.COMPARE_PROGRAMS,
        program_queries=(first_name, second_name),
    )

    updated, question = service._prepare_comparison_follow_up(session, text, parsed)

    assert question is None
    assert updated.program_queries == (first_name, second_name)
    assert updated.metric_codes == ("math_share",)


def test_resolved_program_pair_does_not_require_a_redundant_university_match() -> None:
    first_name = "Интеллектуальные системы обработки информации и управления"
    second_name = "Искусственный интеллект в системах обработки информации и управления"
    ids = {
        first_name: "program:bmstu:09.03.01-02",
        second_name: "program:bmstu:09.03.01-12",
    }

    class Resolver:
        def resolve(self, entity_type, query, *, context=None, limit=10):  # type: ignore[no-untyped-def]
            selected_id = ids.get(query) if entity_type is ResolutionEntityType.PROGRAM else None
            return SimpleNamespace(
                resolution_strategy="deterministic",
                status=ResolutionStatus.RESOLVED if selected_id else ResolutionStatus.NOT_FOUND,
                selected_id=selected_id,
                candidate_hash=None,
            )

    service = object.__new__(AssistantService)
    service._entity_resolver = Resolver()
    session = QuerySession(
        session_id="query-session:" + "e" * 32,
        owner_scope=OWNER,
        intent=ConversationIntent.COMPARE_PROGRAMS,
        entities={
            ResolutionEntityType.UNIVERSITY: ("МГТУ имени Баумана",),
            ResolutionEntityType.PROGRAM: (first_name, second_name),
        },
        metrics=("math_share",),
        missing_slots=(ConversationSlot.ENTITY,),
        next_action=NextAction.ASK_FOR_ENTITY,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    updated = service._resolve_entities(session)

    assert updated.missing_slots == ()
    assert updated.unresolved_entities == ()
    assert updated.entities[ResolutionEntityType.PROGRAM] == tuple(ids.values())
    assert ResolutionEntityType.UNIVERSITY not in updated.entities


def test_bounded_selection_rejects_a_candidate_hash_with_wrong_shape() -> None:
    session = QuerySession(
        session_id="query-session:" + "c" * 32,
        owner_scope=OWNER,
        intent=ConversationIntent.COMPARE_PROGRAMS,
        missing_slots=(ConversationSlot.ENTITY,),
        next_action=NextAction.ASK_FOR_ENTITY,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    try:
        add_bounded_catalog_selection(
            session,
            entity_type=ResolutionEntityType.DIRECTION,
            canonical_id="direction:bmstu:09.03.01",
            candidate_hash="not-a-sha256",
        )
    except ValueError as error:
        assert "candidate hash" in str(error)
    else:
        raise AssertionError("invalid candidate hash was accepted")


def test_policy_follow_up_keeps_rule_context_for_effective_date_question() -> None:
    existing = QuerySession(
        session_id="query-session:" + "f" * 32,
        owner_scope=OWNER,
        intent=ConversationIntent.KNOWLEDGE_POLICY_QUERY,
        policy_query_context=PolicyQueryContext(
            focus=PolicyQueryFocus.CHANGE,
            mentioned_effective_year=PolicyQueryYear(year=2028),
        ),
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    followed_up = _apply_contextual_follow_up(
        RuleBasedQueryParser().parse("А с какого числа это действует?"),
        existing,
        "А с какого числа это действует?",
    )

    assert followed_up.intent is ConversationIntent.KNOWLEDGE_POLICY_QUERY
    assert followed_up.policy_query_context is not None
    assert followed_up.policy_query_context.focus is PolicyQueryFocus.STATUS
    assert followed_up.policy_query_context.mentioned_effective_year == PolicyQueryYear(
        year=2028
    )


def test_policy_history_follow_up_uses_rule_year_not_applicant_year() -> None:
    existing = QuerySession(
        session_id="query-session:" + "9" * 32,
        owner_scope=OWNER,
        intent=ConversationIntent.KNOWLEDGE_POLICY_QUERY,
        policy_query_context=PolicyQueryContext(
            focus=PolicyQueryFocus.APPLICABILITY,
            mentioned_effective_year=PolicyQueryYear(year=2028),
        ),
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    followed_up = _apply_contextual_follow_up(
        RuleBasedQueryParser().parse("А как это правило работало в 2026?"),
        existing,
        "А как это правило работало в 2026?",
    )

    assert followed_up.intent is ConversationIntent.KNOWLEDGE_POLICY_QUERY
    assert followed_up.admission_year is None
    assert followed_up.policy_query_context is not None
    assert followed_up.policy_query_context.focus is PolicyQueryFocus.HISTORY
    assert followed_up.policy_query_context.mentioned_effective_year == PolicyQueryYear(
        year=2026
    )


def test_explicit_new_comparison_does_not_inherit_policy_context() -> None:
    existing = QuerySession(
        session_id="query-session:" + "a" * 32,
        owner_scope=OWNER,
        intent=ConversationIntent.KNOWLEDGE_POLICY_QUERY,
        policy_query_context=PolicyQueryContext(focus=PolicyQueryFocus.STATUS),
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    parsed = RuleBasedQueryParser().parse("А теперь сравни программы ИУ5 и ИУ7")
    followed_up = _apply_contextual_follow_up(
        parsed,
        existing,
        "А теперь сравни программы ИУ5 и ИУ7",
    )

    assert followed_up.intent is ConversationIntent.COMPARE_PROGRAMS
    assert followed_up.policy_query_context is None


def test_natural_difference_question_is_a_comparison_intent() -> None:
    parsed = RuleBasedQueryParser().parse(
        "Чем ИУ5 (09.03.01-02) отличается от ИУ7 (09.03.04-01) по учебным планам?"
    )

    assert parsed.intent is ConversationIntent.COMPARE_PROGRAMS
    assert parsed.program_queries == ("09.03.01-02", "09.03.04-01")


def test_difference_and_similarity_wording_are_recognized_without_fixed_phrases() -> None:
    parser = RuleBasedQueryParser()
    prompts = (
        "В чём разница между 09.03.01-02 и 09.03.04-01?",
        "Что общего у 09.03.01-02 и 09.03.04-01?",
        "Чем направление 09.03.01 отличается от направления 09.03.04?",
    )

    assert all(parser.parse(prompt).intent is ConversationIntent.COMPARE_PROGRAMS for prompt in prompts)


def test_comparison_metric_follow_up_does_not_turn_into_program_discovery() -> None:
    existing = QuerySession(
        session_id="query-session:" + "b" * 32,
        owner_scope=OWNER,
        intent=ConversationIntent.COMPARE_PROGRAMS,
        entities={
            ResolutionEntityType.PROGRAM: (
                "program:bmstu:09.03.01-02",
                "program:bmstu:09.03.01-12",
            )
        },
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    text = "А теперь только по программированию и математике"

    followed_up = _apply_contextual_follow_up(
        RuleBasedQueryParser().parse(text), existing, text
    )

    assert followed_up.intent is ConversationIntent.COMPARE_PROGRAMS
    assert followed_up.metric_codes == ("math_share", "programming_share")
    assert followed_up.replace_metrics is True


def test_short_ai_answer_fills_program_discovery_interest_slot() -> None:
    existing = QuerySession(
        session_id="query-session:" + "c" * 32,
        owner_scope=OWNER,
        intent=ConversationIntent.PROGRAM_DISCOVERY,
        missing_slots=(ConversationSlot.INTERESTS,),
        next_action=NextAction.CLARIFY,
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )

    followed_up = _apply_contextual_follow_up(
        RuleBasedQueryParser().parse("AI"), existing, "AI"
    )

    assert followed_up.intent is ConversationIntent.PROGRAM_DISCOVERY
    assert followed_up.preferred_areas == (
        DisciplineAreaCode.COMPUTER_SCIENCE_DATA,
    )
    assert followed_up.metric_codes == ()


def test_funding_only_follow_up_filters_existing_program_discovery() -> None:
    existing = QuerySession(
        session_id="query-session:" + "d" * 32,
        owner_scope=OWNER,
        intent=ConversationIntent.PROGRAM_DISCOVERY,
        program_discovery_context=ProgramDiscoveryContext(
            preferred_areas=(DisciplineAreaCode.COMPUTER_SCIENCE_DATA,),
            candidate_program_ids=("program:bmstu:09.03.01-02",),
        ),
        created_at=NOW,
        updated_at=NOW,
        expires_at=NOW + timedelta(hours=1),
    )
    text = "А теперь только бюджет"

    followed_up = _apply_contextual_follow_up(
        RuleBasedQueryParser().parse(text), existing, text
    )

    assert followed_up.intent is ConversationIntent.PROGRAM_DISCOVERY
    assert followed_up.funding_type is not None
    assert followed_up.starts_new_task is False
