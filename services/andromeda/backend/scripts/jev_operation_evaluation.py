"""Generate source-backed, bounded Jev evaluation cases and capture live choices.

This is evaluation tooling only. Runtime facts and policies stay in Andromeda's
deterministic modules; provider observations never become labels or source facts.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import logging
import math
import statistics
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from andromeda.infrastructure.config.settings import Settings
from andromeda.infrastructure.jev.adapter import _sanitize_candidate_query
from andromeda.infrastructure.jev.contracts import JevRequestEnvelope
from andromeda.infrastructure.jev.question_registry import QuestionRegistry
from andromeda.infrastructure.jev.typesafe_client import TypeSafeJevTransport
from andromeda.modules.admission_benefits.contracts.public import OlympiadProfile
from andromeda.modules.analytics.domain.metric_registry import MetricRegistry
from andromeda.modules.conversation.contracts.policy import (
    CandidateResolutionOption,
    DecisionModelOperation,
)
from evals.jev.exporters import build_jevcal_bundle

logger = logging.getLogger("andromeda.scripts.jev_operation_evaluation")
MAIN_REGISTRY_PATH = ROOT / "config" / "jev" / "question-definitions.v1.yaml"
ADMISSION_REGISTRY_PATH = (
    ROOT / "config" / "jev" / "question-definitions.admission.v1.yaml"
)
BMSTU_BENEFIT_FIXTURES = (
    ROOT / "tests" / "ingestion" / "fixtures" / "bmstu" / "admission_benefits"
)
LIVE_CASE_PREFIX = "jev-operation-live-v1"
MAX_LIVE_CALLS = 200

_INTENT_CASES: tuple[tuple[str, str], ...] = (
    ("Покажи программы Бауманки по прикладной информатике", "catalog_search"),
    ("Какие направления есть в МГТУ?", "catalog_search"),
    ("Открой список программ по информатике", "catalog_search"),
    ("Найди учебные планы ИУ7", "catalog_search"),
    ("Где больше математики?", "catalog_search"),
    ("Сравни ИУ5 и ИУ7", "comparison"),
    ("Сопоставь две программы по математике и физике", "comparison"),
    ("Какая из этих программ сильнее по программированию?", "comparison"),
    ("Сравнение прикладной информатики Бауманки и ВШЭ", "comparison"),
    ("Сравни эти три направления", "comparison"),
    ("Куда я прохожу с 270 баллами?", "admission_search"),
    ("Русский 90, математика 88, информатика 92 — куда на бюджет?", "admission_search"),
    ("Какие ЕГЭ нужны для поступления на ИУ7?", "admission_search"),
    ("Я призёр олимпиады, есть ли у меня БВИ?", "admission_search"),
    ("Сколько стоит платное обучение на этой программе?", "admission_search"),
    ("Подбери программу с математикой и аналитикой", "recommendation"),
    ("Посоветуй, куда поступать с моими интересами", "recommendation"),
    ("Найди мне подходящие направления", "recommendation"),
    ("Хочу много физики и меньше программирования — что выбрать?", "recommendation"),
    ("Помоги выбрать программу под мои баллы", "recommendation"),
    ("Привет!", "unknown"),
    ("Расскажи анекдот", "unknown"),
    ("Сколько сейчас времени?", "unknown"),
    ("А вот это как?", "unknown"),
    ("Не знаю", "unknown"),
)

_METRIC_CASES: tuple[tuple[str, str], ...] = (
    ("Где больше математических дисциплин?", "mathematics_share"),
    ("Сравни долю математики", "mathematics_share"),
    (
        "Сколько в программе матанализа и алгебры относительно всего плана?",
        "mathematics_share",
    ),
    ("На какой программе больше пишут код?", "programming_share"),
    ("Сравни долю программирования", "programming_share"),
    ("Где сильнее программирование и разработка ПО?", "programming_share"),
    ("Где больше физических дисциплин?", "physics_share"),
    ("Найди программу с меньшей долей физики", "physics_share"),
    ("Сколько физики в учебном плане?", "physics_share"),
    ("Где больше машинного обучения и искусственного интеллекта?", "ai_share"),
    ("Сравни программы по AI", "ai_share"),
    ("В какой программе больше искусственного интеллекта?", "ai_share"),
    ("Где больше статистики и теории вероятностей?", "statistics_share"),
    ("Сравни долю статистических предметов", "statistics_share"),
    ("Сколько статистики в программе?", "statistics_share"),
    ("Где сильнее бизнес-составляющая?", "business_share"),
    ("Сравни долю бизнес-дисциплин", "business_share"),
    ("В какой программе больше предметов про бизнес?", "business_share"),
    ("Сколько всего зачётных единиц в плане?", "total_credits"),
    ("Сравни общий объём программы в ЗЕТ", "total_credits"),
    ("Какой суммарный объём кредитов учебного плана?", "total_credits"),
    ("Сколько стоит обучение на этой программе?", "tuition"),
    ("Сравни стоимость обучения", "tuition"),
    ("Где обучение дороже?", "tuition"),
)

_PRESENTATION_CASES: tuple[tuple[dict[str, object], str], ...] = (
    (
        {
            "comparison_requested": False,
            "report_requested": False,
            "interactive_requested": False,
            "presentation_hint": "Короткий ответ на один факт",
        },
        "text",
    ),
    (
        {
            "comparison_requested": False,
            "report_requested": False,
            "interactive_requested": False,
            "presentation_hint": "Одно предложение без таблицы",
        },
        "text",
    ),
    (
        {
            "comparison_requested": True,
            "report_requested": False,
            "interactive_requested": False,
            "presentation_hint": "Две программы, одна метрика",
        },
        "image",
    ),
    (
        {
            "comparison_requested": True,
            "report_requested": False,
            "interactive_requested": False,
            "presentation_hint": "Сравнительная карточка для двух вариантов",
        },
        "image",
    ),
    (
        {
            "comparison_requested": False,
            "report_requested": False,
            "interactive_requested": False,
            "presentation_hint": "Короткий рейтинг из пяти программ",
        },
        "image_collection",
    ),
    (
        {
            "comparison_requested": False,
            "report_requested": False,
            "interactive_requested": False,
            "presentation_hint": "Небольшой список результатов",
        },
        "image_collection",
    ),
    (
        {
            "comparison_requested": True,
            "report_requested": True,
            "interactive_requested": False,
            "presentation_hint": "Подробный многостраничный статический отчёт",
        },
        "pdf",
    ),
    (
        {
            "comparison_requested": True,
            "report_requested": True,
            "interactive_requested": False,
            "presentation_hint": "Полное исследование трёх программ",
        },
        "pdf",
    ),
    (
        {
            "comparison_requested": True,
            "report_requested": False,
            "interactive_requested": True,
            "presentation_hint": "Пользователь будет менять фильтры и сравнивать варианты",
        },
        "mini_app",
    ),
    (
        {
            "comparison_requested": False,
            "report_requested": False,
            "interactive_requested": True,
            "presentation_hint": "Интерактивный подбор с несколькими фильтрами",
        },
        "mini_app",
    ),
)


class OperationEvaluationError(RuntimeError):
    """Raised when a live capture or its bounded inputs are not trustworthy."""


def build_cases(
    definition_id: str,
    registry: QuestionRegistry,
    *,
    count: int = 120,
) -> tuple[dict[str, object], ...]:
    """Create deterministic gold-labelled cases for an existing registry entry."""

    definition = registry.get(definition_id)
    if definition.operation == DecisionModelOperation.RESOLVE_INTENT.value:
        return _static_cases(definition, _INTENT_CASES, "intent")
    if definition.operation == DecisionModelOperation.RESOLVE_METRIC.value:
        return _static_cases(definition, _METRIC_CASES, "metric_code")
    if definition.operation == DecisionModelOperation.CHOOSE_PRESENTATION.value:
        return tuple(
            _case(
                definition,
                f"{LIVE_CASE_PREFIX}-presentation-{index:03d}",
                inputs,
                {"response_format": expected},
            )
            for index, (inputs, expected) in enumerate(_PRESENTATION_CASES, start=1)
        )
    if definition.operation == DecisionModelOperation.RESOLVE_OLYMPIAD_PROFILE.value:
        if count < 40 or count > MAX_LIVE_CALLS:
            raise ValueError(
                f"Olympiad case count must be between 40 and {MAX_LIVE_CALLS}"
            )
        return _bmstu_olympiad_cases(definition, count=count)
    raise ValueError(
        f"no evaluation corpus builder for operation {definition.operation}"
    )


def _static_cases(
    definition: Any,
    labelled_phrases: tuple[tuple[str, str], ...],
    expected_key: str,
) -> tuple[dict[str, object], ...]:
    cases: list[dict[str, object]] = []
    candidates: tuple[str, ...] = ()
    if expected_key == "metric_code":
        candidates = (
            "mathematics_share",
            "programming_share",
            "physics_share",
            "ai_share",
            "statistics_share",
            "business_share",
            "total_credits",
            "tuition",
        )
        registry = MetricRegistry()
        for candidate in candidates:
            registry.get(candidate)
    for index, (text, label) in enumerate(labelled_phrases, start=1):
        input_data: dict[str, object] = {"text": text}
        if candidates:
            input_data["candidates"] = list(candidates)
        expected: dict[str, object] = {expected_key: label}
        cases.append(
            _case(
                definition,
                f"{LIVE_CASE_PREFIX}-{definition.operation}-{index:03d}",
                input_data,
                expected,
            )
        )
    return tuple(cases)


def _bmstu_olympiad_cases(
    definition: Any, *, count: int
) -> tuple[dict[str, object], ...]:
    from andromeda.ingestion.universities.bmstu.adapter import BmstuUniversityAdapter

    adapter = BmstuUniversityAdapter()
    try:
        captured = adapter.capture(
            mode="fixture",
            admission_benefits_fixture_dir=BMSTU_BENEFIT_FIXTURES,
            admission_year=2026,
        )
        _, canonical = adapter.parse(captured, admission_year=2026)
    finally:
        adapter.close()
    snapshot = canonical.admission_benefits
    if snapshot is None or snapshot.admission_year != 2026:
        raise OperationEvaluationError(
            "official BMSTU 2026 fixture produced no profile snapshot"
        )
    olympiads = {str(item.id): item for item in snapshot.olympiads}
    profiles = tuple(
        sorted(
            snapshot.olympiad_profiles,
            key=lambda item: (item.profile_name.casefold(), str(item.id)),
        )
    )
    if len(profiles) < 2 or any(
        str(profile.olympiad_id) not in olympiads for profile in profiles
    ):
        raise OperationEvaluationError(
            "source-backed Olympiad/profile candidates are incomplete"
        )
    profile_labels = {
        str(
            profile.id
        ): f"{olympiads[str(profile.olympiad_id)].official_name} — {profile.profile_name}"
        for profile in profiles
    }
    groups: dict[str, list[OlympiadProfile]] = {}
    for profile in profiles:
        groups.setdefault(str(profile.olympiad_id), []).append(profile)
    target_count = count - max(1, count // 12)
    train_variants = (
        "Я призёр олимпиады {olympiad}, профиль {profile}",
        "Олимпиада {olympiad}; направление — {profile}",
        "У меня диплом победителя: {olympiad}, {profile}",
        "Результат по профилю «{profile}» в олимпиаде {olympiad}",
        "Я участвовал в {olympiad}, профиль {profile}",
    )
    heldout_variants = (
        "Подскажи про {olympiad}: у меня профиль {profile}",
        "Я занял призовое место на олимпиаде «{olympiad}» по направлению «{profile}»",
        "Диплом {profile} — олимпиада {olympiad}",
        "Профиль: {profile}; состязание: {olympiad}",
        "Хочу проверить диплом победителя: {profile} / {olympiad}",
    )
    cases: list[dict[str, object]] = []
    for index in range(target_count):
        target = profiles[index % len(profiles)]
        target_id = str(target.id)
        profile_round = index // len(profiles)
        desired_split = "train" if profile_round < 5 else "heldout"
        variants = train_variants if desired_split == "train" else heldout_variants
        others = [item for item in profiles if item.id != target.id]
        offset = (index * 3) % len(others)
        distractors = [
            others[(offset + step) % len(others)] for step in range(min(5, len(others)))
        ]
        selected = [target, *distractors]
        rotate_by = index % len(selected)
        selected = selected[rotate_by:] + selected[:rotate_by]
        olympiad = olympiads[str(target.olympiad_id)]
        wording = variants[profile_round % len(variants)].format(
            olympiad=olympiad.official_name,
            profile=target.profile_name,
        )
        case_id = _case_id_for_split(
            f"{LIVE_CASE_PREFIX}-olympiad-profile-{len(cases) + 1:03d}",
            desired_split,
        )
        provenance = _source_provenance(target)
        cases.append(
            _case(
                definition,
                case_id,
                {
                    "text": wording,
                    "candidates": [
                        {
                            "candidate_id": str(item.id),
                            "label": profile_labels[str(item.id)],
                        }
                        for item in selected
                    ],
                },
                {"candidate_id": target_id},
                provenance=provenance,
            )
        )

    ambiguous_groups = [items for items in groups.values() if len(items) > 1]
    for index in range(count - len(cases)):
        desired_split = "train" if index < (count - len(cases)) // 2 else "heldout"
        if ambiguous_groups:
            group = ambiguous_groups[index % len(ambiguous_groups)]
            selected = group[:8]
            olympiad = olympiads[str(selected[0].olympiad_id)]
            wording = (
                f"Расскажи про олимпиаду {olympiad.official_name}"
                if index % 2 == 0
                else f"Я участвовал в {olympiad.official_name}, какой у неё профиль?"
            )
        else:
            selected = list(profiles[: min(6, len(profiles))])
            wording = "Я участвовал в олимпиаде, но не помню её профиль"
        case_id = _case_id_for_split(
            f"{LIVE_CASE_PREFIX}-olympiad-ambiguous-{index + 1:03d}",
            desired_split,
        )
        cases.append(
            _case(
                definition,
                case_id,
                {
                    "text": wording,
                    "candidates": [
                        {
                            "candidate_id": str(item.id),
                            "label": profile_labels[str(item.id)],
                        }
                        for item in selected
                    ],
                },
                {"candidate_id": None},
                provenance=tuple(
                    item for profile in selected for item in _source_provenance(profile)
                ),
            )
        )
    if len(cases) != count:
        raise OperationEvaluationError(
            "BMSTU case generator did not meet requested count"
        )
    return tuple(cases)


def _source_provenance(profile: OlympiadProfile) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "url": str(item.source.url),
            "content_sha256": str(item.source_snapshot_hash),
            "document_title": item.document_title,
            "document_kind": item.document_kind,
            "appendix_number": item.appendix_number,
            "page": item.page,
            "table": item.table,
            "row": item.row,
            "section": item.section,
        }
        for item in profile.provenance
    )


def _case(
    definition: Any,
    case_id: str,
    input_data: dict[str, object],
    expected: dict[str, object],
    *,
    provenance: tuple[dict[str, object], ...] = (),
) -> dict[str, object]:
    try:
        from jevcal.metrics import in_holdout  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - guarded by evaluation extra
        raise OperationEvaluationError(
            "install the evaluation extra with jevcal"
        ) from exc
    return {
        "case_id": case_id,
        "definition_id": definition.definition_id,
        "definition_version": definition.version,
        "split": "heldout" if in_holdout(case_id, 0.5, 7) else "train",
        "input": input_data,
        "expected": expected,
        "source_provenance": list(provenance),
    }


def _case_id_for_split(base: str, split: str) -> str:
    """Find a stable row ID in an upstream jevcal split for group holdout."""

    for suffix in range(10_000):
        case_id = f"{base}-{suffix:04d}"
        if _split_for(case_id) == split:
            return case_id
    raise OperationEvaluationError(f"could not assign case ID to {split} split")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--definition-id", required=True)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--generate-cases", type=Path)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--count", type=int, default=120)
    parser.add_argument("--max-live-calls", type=int, default=MAX_LIVE_CALLS)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    registry_path = args.registry or (
        ADMISSION_REGISTRY_PATH
        if args.definition_id == "olympiad-profile-resolution.v1"
        else MAIN_REGISTRY_PATH
    )
    registry = QuestionRegistry.from_file(registry_path)
    definition = registry.get(args.definition_id)
    if args.generate_cases is not None:
        generated_cases = build_cases(args.definition_id, registry, count=args.count)
        _write_new_jsonl(args.generate_cases, generated_cases)
        print(
            json.dumps(
                {
                    "generated": len(generated_cases),
                    "definition_id": args.definition_id,
                },
                indent=2,
            )
        )
        return 0
    if args.cases is None or args.observations is None:
        raise SystemExit("--cases and --observations are required for a live capture")
    if args.cases.resolve() == args.observations.resolve():
        raise SystemExit("cases and observations must use distinct paths")
    if args.max_live_calls < 1 or args.max_live_calls > MAX_LIVE_CALLS:
        raise SystemExit(f"max-live-calls must be between 1 and {MAX_LIVE_CALLS}")
    if not 0 < args.timeout_seconds <= 30:
        raise SystemExit("timeout must be greater than zero and at most 30 seconds")
    if args.observations.exists():
        raise SystemExit("refusing to overwrite an existing observations file")
    cases = _read_jsonl(args.cases)
    if not cases or len(cases) > args.max_live_calls:
        raise SystemExit("case count is empty or exceeds the explicit live-call budget")
    _validate_cases(cases, definition, registry)

    settings = Settings.from_environment()
    if settings.jev_api_key is None:
        raise SystemExit("JEV_API_KEY or TYPESAFE_API_KEY is required in this process")
    try:
        from typesafe_sdk import RetryPolicy, TypeSafeClient, TypeSafeError
    except ImportError as exc:  # pragma: no cover - optional evaluation tooling
        raise SystemExit("install the official TypeSafe SDK extra") from exc

    def no_retry_client(**kwargs: Any) -> Any:
        return TypeSafeClient(
            **kwargs,
            retry=RetryPolicy(max_retries=0, timeout=args.timeout_seconds),
        )

    transport = TypeSafeJevTransport(
        api_key=settings.jev_api_key,
        endpoint=settings.jev_endpoint,
        model=settings.jev_model,
        registry=registry,
        timeout_seconds=args.timeout_seconds,
        client_factory=no_retry_client,
    )
    endpoint_host = urlsplit(settings.jev_endpoint).hostname or "unknown"
    observations: list[dict[str, object]] = []
    latencies: list[int] = []
    correct_count = 0
    try:
        if not transport.health_check():
            raise OperationEvaluationError(
                "provider health check or requested model check failed"
            )
        bundle = build_jevcal_bundle(
            registry, tuple(cases), definition_ids=(definition.definition_id,)
        )
        criteria = bundle.questions[definition.definition_id]["criteria"]
        if not isinstance(criteria, dict) or any(
            not isinstance(label, str) for label in criteria
        ):
            raise OperationEvaluationError(
                "jevcal exporter returned invalid choice criteria"
            )
        all_labels = tuple(sorted(criteria))
        for index, case in enumerate(cases, start=1):
            started = time.monotonic()
            try:
                response = transport.request_envelope(
                    _request_for_case(
                        case, definition, timeout_seconds=args.timeout_seconds
                    )
                )
            except TypeSafeError as exc:
                raise OperationEvaluationError(
                    f"provider call {index}/{len(cases)} failed: {type(exc).__name__}"
                ) from None
            latency_ms = int((time.monotonic() - started) * 1000)
            if response.failure is not None:
                raise OperationEvaluationError(
                    f"provider call {index}/{len(cases)} failed: {response.failure.reason.value}"
                )
            evidence = response.evidence
            if evidence is None or evidence.answer_kind != "ChoiceAnswer":
                raise OperationEvaluationError(
                    "response lacks complete Choice evidence"
                )
            prediction = evidence.answer_value
            if not isinstance(prediction, str):
                raise OperationEvaluationError("provider choice is not a string label")
            expected = case["expected"]
            if not isinstance(expected, dict):
                raise OperationEvaluationError("case expected output must be an object")
            case_input = case.get("input")
            if not isinstance(case_input, dict):
                raise OperationEvaluationError("case input must be an object")
            gold = _gold_label(definition.operation, expected)
            options = _case_options(definition, case_input)
            probabilities = _validate_probabilities(evidence.probabilities, options)
            expanded_probabilities = {
                label: probabilities.get(label, 0.0) for label in all_labels
            }
            if prediction not in options:
                raise OperationEvaluationError(
                    "provider returned an answer outside the supplied choices"
                )
            correct = prediction == gold
            correct_count += int(correct)
            latencies.append(latency_ms)
            observations.append(
                {
                    "schema_version": "jev-live-observation.v1",
                    "case_id": case["case_id"],
                    "definition_id": definition.definition_id,
                    "definition_version": definition.version,
                    "split": case["split"],
                    "provider": "polza" if endpoint_host == "polza.ai" else "typesafe",
                    "endpoint_host": endpoint_host,
                    "model_requested": settings.jev_model,
                    "model_observed": response.identity.model_version,
                    "gold": gold,
                    "prediction": prediction,
                    "correct": correct,
                    "confidence": evidence.confidence,
                    "probabilities": expanded_probabilities,
                    "option_ids": list(options),
                    "latency_ms": latency_ms,
                    "usage": {
                        "input_tokens": response.usage.input_tokens,
                        "output_tokens": response.usage.output_tokens,
                    },
                    "capture_method": "official-typesafe-sdk-system-one",
                    "captured_at": datetime.now(UTC).isoformat(timespec="seconds"),
                }
            )
            if index % 10 == 0 or index == len(cases):
                logger.info(
                    "jev_live_evaluation_progress definition_id=%s completed=%d planned=%d accuracy=%.3f latency_ms_p50=%d",
                    definition.definition_id,
                    index,
                    len(cases),
                    correct_count / index,
                    int(statistics.median(latencies)),
                )
    finally:
        transport.close()

    observed_models = {str(row["model_observed"]) for row in observations}
    if len(observed_models) != 1 or "unknown" in observed_models:
        raise OperationEvaluationError(
            "live responses do not have one identifiable model version"
        )
    _write_new_jsonl(args.observations, observations)
    report = {
        "status": "captured_live_observations",
        "definition_id": definition.definition_id,
        "cases": len(cases),
        "correct": correct_count,
        "accuracy": correct_count / len(cases),
        "heldout": sum(case["split"] == "heldout" for case in cases),
        "provider": "polza" if endpoint_host == "polza.ai" else "typesafe",
        "endpoint_host": endpoint_host,
        "model_requested": settings.jev_model,
        "model_observed": next(iter(observed_models)),
        "typesafe_sdk_version": importlib.metadata.version("typesafe-sdk"),
        "jevcal_version": importlib.metadata.version("jevcal"),
        "latency_ms_p50": int(statistics.median(latencies)),
        "latency_ms_p95": _percentile(latencies, 0.95),
        "input_tokens": _token_count(observations, "input_tokens"),
        "output_tokens": _token_count(observations, "output_tokens"),
        "prediction_counts": dict(
            Counter(str(row["prediction"]) for row in observations)
        ),
        "registry_hash": registry.content_hash(),
        "cases_sha256": _hash_file(args.cases),
        "observations_sha256": _hash_file(args.observations),
        "observations_path": str(args.observations),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _validate_cases(
    cases: list[dict[str, object]], definition: Any, registry: QuestionRegistry
) -> None:
    ids: set[str] = set()
    for case in cases:
        case_id = case.get("case_id")
        input_data = case.get("input")
        expected = case.get("expected")
        if not isinstance(case_id, str) or not case_id or case_id in ids:
            raise OperationEvaluationError("case IDs must be present and unique")
        ids.add(case_id)
        if (
            case.get("definition_id") != definition.definition_id
            or case.get("definition_version") != definition.version
        ):
            raise OperationEvaluationError(
                "case definition/version differs from registry"
            )
        if not isinstance(input_data, dict) or not isinstance(expected, dict):
            raise OperationEvaluationError(
                "case input and expected values must be objects"
            )
        if case.get("split") != _split_for(case_id):
            raise OperationEvaluationError(
                f"case {case_id} split differs from upstream jevcal"
            )
        if _gold_label(definition.operation, expected) not in _case_options(
            definition, input_data
        ):
            raise OperationEvaluationError(
                f"gold label is not available to the model: {case_id}"
            )
        # The exporter enforces both registry membership and dynamic candidate scope.
    build_jevcal_bundle(
        registry, tuple(cases), definition_ids=(definition.definition_id,)
    )


def _request_for_case(
    case: dict[str, object], definition: Any, *, timeout_seconds: float = 20.0
) -> JevRequestEnvelope:
    payload = case.get("input")
    if not isinstance(payload, dict):
        raise OperationEvaluationError("case input must be an object")
    bounded_payload = dict(payload)
    if definition.operation == DecisionModelOperation.RESOLVE_OLYMPIAD_PROFILE.value:
        text = bounded_payload.get("text")
        candidates = bounded_payload.get("candidates")
        if not isinstance(text, str) or not isinstance(candidates, list):
            raise OperationEvaluationError(
                "Olympiad case needs text and candidate objects"
            )
        options = tuple(
            CandidateResolutionOption(
                candidate_id=str(candidate["candidate_id"]),
                label=str(candidate["label"]),
            )
            for candidate in candidates
            if isinstance(candidate, dict)
            and isinstance(candidate.get("candidate_id"), str)
            and isinstance(candidate.get("label"), str)
        )
        if len(options) != len(candidates):
            raise OperationEvaluationError("Olympiad candidate payload is malformed")
        sanitized_text = _sanitize_candidate_query(text, options)
        if not sanitized_text:
            raise OperationEvaluationError(
                "query has no source-candidate overlap and must bypass Jev"
            )
        bounded_payload["text"] = sanitized_text
    return JevRequestEnvelope(
        definition_id=definition.definition_id,
        definition_version=definition.version,
        definition_kind=definition.kind,
        operation=DecisionModelOperation(definition.operation),
        redacted_payload=bounded_payload,
        correlation_id=f"jev-eval-{case['case_id']}",
        timeout_seconds=timeout_seconds,
        timeout_class=definition.timeout_class,
        pii_policy=definition.pii_policy,
        output_schema=definition.output_schema,
    )


def _case_options(definition: Any, input_data: dict[str, object]) -> tuple[str, ...]:
    if definition.operation == DecisionModelOperation.RESOLVE_INTENT.value:
        return tuple(option.code for option in definition.options)
    if definition.operation == DecisionModelOperation.CHOOSE_PRESENTATION.value:
        labels = definition.output_schema.allowed_values
        if not all(isinstance(label, str) for label in labels):
            raise OperationEvaluationError(
                "presentation registry contains invalid choices"
            )
        return tuple(labels)
    if definition.operation == DecisionModelOperation.RESOLVE_METRIC.value:
        candidates = input_data.get("candidates")
        if not isinstance(candidates, list) or not candidates or len(candidates) > 8:
            raise OperationEvaluationError(
                "metric candidate set must contain 1–8 values"
            )
        if any(not isinstance(item, str) or not item for item in candidates):
            raise OperationEvaluationError(
                "metric candidate IDs must be non-empty strings"
            )
        metric_ids = tuple(item for item in candidates if isinstance(item, str))
        if len(metric_ids) != len(set(metric_ids)) or "unresolved" in metric_ids:
            raise OperationEvaluationError(
                "metric candidate IDs must be unique and not reserved"
            )
        return (*metric_ids, "unresolved")
    if definition.operation == DecisionModelOperation.RESOLVE_OLYMPIAD_PROFILE.value:
        candidates = input_data.get("candidates")
        if not isinstance(candidates, list) or not 1 <= len(candidates) <= 8:
            raise OperationEvaluationError(
                "Olympiad candidate set must contain 1–8 values"
            )
        ids: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise OperationEvaluationError("Olympiad candidates must be objects")
            candidate_id = candidate.get("candidate_id")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise OperationEvaluationError(
                    "Olympiad candidate IDs must be non-empty strings"
                )
            ids.append(candidate_id)
        if len(ids) != len(set(ids)) or "unresolved" in ids:
            raise OperationEvaluationError(
                "Olympiad candidate IDs are duplicated or reserved"
            )
        return (*tuple(ids), "unresolved")
    raise OperationEvaluationError(
        f"operation is not a live Choice evaluator: {definition.operation}"
    )


def _gold_label(operation: str, expected: dict[str, object]) -> str:
    key = {
        DecisionModelOperation.RESOLVE_INTENT.value: "intent",
        DecisionModelOperation.RESOLVE_METRIC.value: "metric_code",
        DecisionModelOperation.CHOOSE_PRESENTATION.value: "response_format",
        DecisionModelOperation.RESOLVE_OLYMPIAD_PROFILE.value: "candidate_id",
    }.get(operation)
    if key is None:
        raise OperationEvaluationError(
            f"unsupported operation for gold labels: {operation}"
        )
    value = expected.get(key)
    if value is None and operation in {
        DecisionModelOperation.RESOLVE_METRIC.value,
        DecisionModelOperation.RESOLVE_OLYMPIAD_PROFILE.value,
    }:
        return "unresolved"
    if not isinstance(value, str) or not value:
        raise OperationEvaluationError(f"expected.{key} must be a non-empty string")
    return value


def _validate_probabilities(
    probabilities: dict[str, float], expected: tuple[str, ...]
) -> dict[str, float]:
    if set(probabilities) != set(expected):
        raise OperationEvaluationError(
            "provider probability labels do not match this case's bounded options"
        )
    if any(
        not math.isfinite(value) or not 0 <= value <= 1
        for value in probabilities.values()
    ):
        raise OperationEvaluationError("provider returned an invalid probability value")
    if not math.isclose(sum(probabilities.values()), 1.0, abs_tol=0.02):
        raise OperationEvaluationError(
            "provider probability vector does not sum to one"
        )
    return {key: probabilities[key] for key in sorted(probabilities)}


def _split_for(case_id: str) -> str:
    try:
        from jevcal.metrics import in_holdout
    except ImportError as exc:  # pragma: no cover
        raise OperationEvaluationError(
            "install the evaluation extra with jevcal"
        ) from exc
    return "heldout" if in_holdout(case_id, 0.5, 7) else "train"


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise OperationEvaluationError("each JSONL record must be an object")
            rows.append(value)
    return rows


def _write_new_jsonl(
    path: Path, rows: tuple[dict[str, object], ...] | list[dict[str, object]]
) -> None:
    if path.exists():
        raise OperationEvaluationError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _hash_file(path: Path) -> str:
    content = path.read_bytes().replace(b"\r\n", b"\n")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _percentile(values: list[int], fraction: float) -> int:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def _token_count(observations: list[dict[str, object]], key: str) -> int:
    total = 0
    for row in observations:
        usage = row.get("usage")
        value = usage.get(key) if isinstance(usage, dict) else None
        if isinstance(value, int) and value >= 0:
            total += value
    return total


if __name__ == "__main__":  # pragma: no cover - exercised by CLI/CI invocations
    raise SystemExit(main())
