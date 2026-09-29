from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from hashlib import sha256
from pathlib import Path
from typing import cast

from pydantic import HttpUrl

from andromeda.ingestion.contracts.admission_benefits import AdmissionBenefitsSnapshot

from ....modules.admission_benefits.contracts.provenance import BenefitProvenance
from ....modules.admission_benefits.contracts.status import BenefitPolicyVersion
from ....modules.disciplines.contracts.public import Discipline
from ....modules.disciplines.services.classifier import RuleBasedDisciplineClassifier
from ....shared.contracts.enums import SourceKind
from ....shared.contracts.errors import ContractError
from ....shared.contracts.ids import IngestRunId
from ....shared.contracts.provenance import SourceAttribution
from ....shared.contracts.versions import (
    ADMISSION_BENEFITS_PARSER_VERSION,
    ADMISSION_BENEFITS_POLICY_VERSION,
    ADMISSION_BENEFITS_SCHEMA_VERSION,
)
from ...contracts.normalized import CanonicalSnapshot
from ...contracts.raw import (
    AdmissionBenefitParserDiagnostic,
    RawAdmissionBenefitDocument,
    RawAdmissionBenefitRecord,
    RawAdmissionPassingScore,
    RawAdmissionRecord,
    RawIndividualAchievementRecord,
    RawProgramRecord,
    RawSourceGap,
    RawSourceSnapshot,
    RawTracerBundle,
    SourceLocator,
)
from ...contracts.source import CapturedSources, source_gap_reference
from .admission_benefits.capture import INDEX_SOURCE_KIND, BmstuAdmissionBenefitsCapture
from .admission_benefits.coverage import build_coverage
from .admission_benefits.index import discover_document_manifest
from .admission_benefits.source_catalog import BMSTU_ADMISSION_DOCUMENTS_INDEX_URL
from .admission_benefits.source_manifest import (
    BmstuAdmissionDocumentKind,
    BmstuAdmissionSourceManifest,
)
from .capture import BmstuSource, _detail_plan_records, parse_orders_manifest
from .identity import direction_codes as extract_direction_codes
from .identity import map_source_program_code
from .mappings.discipline_areas import BMSTU_DISCIPLINE_AREA_OVERRIDES
from .normalizers.admission_benefits import (
    OlympiadProfileSourceEnrichment,
    normalize_individual_achievements,
    normalize_olympiad_benefits,
)
from .normalizers.admissions import normalize_admissions
from .normalizers.campus import normalize_campus_points
from .normalizers.canonical import normalize_bundle
from .normalizers.events import normalize_events
from .parser.admission_benefits import BmstuAdmissionBenefitsParser
from .parser.admission_olympiads import (
    BmstuOlympiadProfileParseResult,
    parse_olympiad_profile_source,
)
from .parser.admission_orders import iter_pdf_pages, parse_admission_order_document
from .parser.admission_rules import parse_admission_rule_policy
from .parser.admissions import parse_detail_admissions
from .parser.campus import load_campus_fixture, parse_campus_points
from .parser.catalog import parse_catalog_direction_codes, parse_catalog_direction_index
from .parser.events import load_event_fixture, parse_events
from .parser.individual_achievements import parse_individual_achievement_tables
from .parser.special_olympiads import parse_special_olympiad_tables
from .parser.tracer import parse_captured
from .pdf import extract_pdf_pages_text, extract_pdf_tables, is_pdf
from .selectors import (
    DEFAULT_CAMPUS_FIXTURE_DIR,
    DEFAULT_EVENT_FIXTURE_DIR,
    DEFAULT_FIXTURE_DIR,
    select_program_codes,
)
from .source_metadata import classify_order_document

fetch_logger = logging.getLogger("andromeda.ingestion.bmstu.fetch")
select_logger = logging.getLogger("andromeda.ingestion.bmstu.select")
parse_logger = logging.getLogger("andromeda.ingestion.bmstu.parse")
normalize_logger = logging.getLogger("andromeda.ingestion.bmstu.normalize")


class BmstuUniversityAdapter:
    """Typed BMSTU boundary for source capture, parsing, and normalization."""

    def __init__(
        self,
        fetcher: object | None = None,
        admission_benefits_capture: BmstuAdmissionBenefitsCapture | None = None,
    ) -> None:
        self._source = BmstuSource(fetcher=fetcher)  # type: ignore[arg-type]
        self._classifier = RuleBasedDisciplineClassifier(
            BMSTU_DISCIPLINE_AREA_OVERRIDES
        )
        self._admission_benefits_capture = admission_benefits_capture

    def close(self) -> None:
        self._source.close()
        if self._admission_benefits_capture is not None:
            self._admission_benefits_capture.close()

    def capture(
        self,
        mode: str = "fixture",
        fixture_dir: Path | None = None,
        event_fixture_dir: Path | None = None,
        campus_fixture_dir: Path | None = None,
        admission_benefits_fixture_dir: Path | None = None,
        admission_year: int = 2026,
        include_admission_benefits: bool = False,
    ) -> CapturedSources:
        fetch_logger.debug("stage=capture mode=%s", mode)
        captured = self._source.capture(
            mode=mode, fixture_dir=fixture_dir or DEFAULT_FIXTURE_DIR
        )
        snapshots = captured.snapshots
        if mode == "fixture":
            event_snapshot = load_event_fixture(
                event_fixture_dir or DEFAULT_EVENT_FIXTURE_DIR
            )
            campus_snapshot = load_campus_fixture(
                campus_fixture_dir or DEFAULT_CAMPUS_FIXTURE_DIR
            )
            snapshots += (event_snapshot, campus_snapshot)
        source_gaps = list(captured.source_gaps)
        should_capture_benefits = (
            admission_benefits_fixture_dir is not None or include_admission_benefits
        )
        if should_capture_benefits:
            if self._admission_benefits_capture is None:
                self._admission_benefits_capture = BmstuAdmissionBenefitsCapture()
            benefits = self._admission_benefits_capture.capture(
                mode=mode,
                fixture_dir=admission_benefits_fixture_dir,
                admission_year=admission_year,
            )
            snapshots += benefits.captured.snapshots
            source_gaps.extend(benefits.captured.source_gaps)
        result = CapturedSources(snapshots=snapshots, source_gaps=tuple(source_gaps))
        fetch_logger.info(
            "stage=capture_complete mode=%s snapshots=%d event_source=%s campus_source=%s",
            mode,
            len(result.snapshots),
            mode == "fixture",
            mode == "fixture",
        )
        return result

    def parse(
        self,
        captured: CapturedSources,
        program_codes: Sequence[str] | None = None,
        source_run_id: IngestRunId | None = None,
        admission_year: int = 2026,
    ) -> tuple[RawTracerBundle, CanonicalSnapshot]:
        selected = (
            select_program_codes(tuple(program_codes))
            if program_codes is not None
            else _fixture_documented_codes(captured)
        )
        campus_source_kind = "bmstu_campus_points"
        parser_snapshots = tuple(
            snapshot
            for snapshot in captured.snapshots
            if snapshot.source_kind != campus_source_kind
        )
        parser_captured = CapturedSources(
            snapshots=parser_snapshots, source_gaps=captured.source_gaps
        )
        select_logger.debug(
            "stage=selected source_snapshots=%d programs=%s",
            len(parser_snapshots),
            len(selected) if selected is not None else "discovery",
        )
        parse_logger.debug(
            "stage=parse source_snapshots=%d programs=%s",
            len(parser_snapshots),
            len(selected) if selected is not None else "discovery",
        )
        raw = parse_captured(parser_captured, program_codes=selected).model_copy(
            update={"snapshots": captured.snapshots}
        )
        admission_records = tuple(
            record
            for detail_snapshot in captured.by_kind("bmstu_major_detail")
            for record in parse_detail_admissions(detail_snapshot, selected)
        )
        order_records, order_gaps = _parse_order_admissions(captured, raw.programs)
        admission_records, admission_gaps = _canonicalize_admission_records(
            (*admission_records, *order_records),
            raw.programs,
        )
        event_snapshots = captured.by_kind("bmstu_events")
        if len(event_snapshots) > 1:
            raise ValueError("expected at most one BMSTU event source snapshot")
        event_records = parse_events(event_snapshots[0]) if event_snapshots else ()
        campus_snapshots = captured.by_kind(campus_source_kind)
        if len(campus_snapshots) > 1:
            raise ValueError("expected at most one BMSTU campus source snapshot")
        campus_records = (
            parse_campus_points(campus_snapshots[0]) if campus_snapshots else ()
        )
        raw = raw.model_copy(
            update={
                "admissions": admission_records,
                "source_gaps": (*raw.source_gaps, *order_gaps, *admission_gaps),
                "events": event_records,
                "campus_points": campus_records,
            }
        )
        benefit_records, benefit_diagnostics, benefit_snapshot = (
            _parse_admission_benefits(
                captured,
                source_run_id=source_run_id or _derived_benefit_run_id(captured),
                university_id="university:bmstu",
                known_direction_codes=(
                    frozenset(
                        direction.code
                        for direction in (raw.directions or (raw.direction,))
                    )
                    | parse_catalog_direction_codes(
                        captured.by_kind("bmstu_major_catalog")
                    )
                ),
                direction_index=parse_catalog_direction_index(
                    captured.by_kind("bmstu_major_catalog")
                ),
                admission_year=admission_year,
            )
        )
        raw = raw.model_copy(
            update={
                "admission_benefit_records": benefit_records,
                "admission_benefit_diagnostics": benefit_diagnostics,
                "admission_benefit_coverage": benefit_snapshot.coverage
                if benefit_snapshot
                else None,
            }
        )
        canonical = normalize_bundle(raw)
        if campus_snapshots and not any(
            source.kind is SourceKind.BMSTU_CAMPUS_POINTS
            for source in canonical.sources
        ):
            campus_snapshot = campus_snapshots[0]
            canonical = canonical.model_copy(
                update={
                    "sources": (
                        *canonical.sources,
                        SourceAttribution(
                            kind=SourceKind.BMSTU_CAMPUS_POINTS,
                            url=campus_snapshot.requested_url,
                            captured_at=campus_snapshot.captured_at,
                            content_sha256=campus_snapshot.content_sha256,
                        ),
                    )
                }
            )
        order_source_snapshots = (
            *captured.by_kind("bmstu_admission_orders_index"),
            *captured.by_kind("bmstu_admission_orders_document"),
        )
        if order_source_snapshots:
            existing_sources = {
                (str(source.kind), str(source.url), source.content_sha256)
                for source in canonical.sources
            }
            missing_order_sources = tuple(
                snapshot
                for snapshot in order_source_snapshots
                if (
                    snapshot.source_kind,
                    str(snapshot.requested_url),
                    snapshot.content_sha256,
                )
                not in existing_sources
            )
            canonical = canonical.model_copy(
                update={
                    "sources": (
                        *canonical.sources,
                        *(
                            SourceAttribution(
                                kind=SourceKind(snapshot.source_kind),
                                url=snapshot.requested_url,
                                captured_at=snapshot.captured_at,
                                content_sha256=snapshot.content_sha256,
                            )
                            for snapshot in missing_order_sources
                        ),
                    )
                }
            )
        classified_disciplines = tuple(
            Discipline.model_validate(
                {
                    **discipline.model_dump(),
                    "area_weights": self._classifier.classify(discipline.name),
                }
            )
            for discipline in canonical.disciplines
        )
        classification_outcomes = tuple(
            self._classifier.classify_with_outcome(
                discipline.name,
                discipline_id=discipline.id,
            )
            for discipline in canonical.disciplines
        )
        canonical = CanonicalSnapshot.model_validate(
            {
                **canonical.model_dump(),
                "disciplines": classified_disciplines,
                "classification_outcomes": classification_outcomes,
                "source_gaps": raw.source_gaps,
                "admissions": normalize_admissions(
                    raw.admissions,
                    programs=canonical.programs,
                    snapshots=raw.snapshots,
                ),
                "events": normalize_events(
                    raw.events,
                    programs=canonical.programs,
                    snapshots=raw.snapshots,
                    known_program_codes=tuple(
                        program.code for program in canonical.programs
                    ),
                ),
                "campus_points": normalize_campus_points(
                    raw.campus_points,
                    programs=canonical.programs,
                    snapshots=raw.snapshots,
                    known_program_codes=tuple(
                        program.code for program in canonical.programs
                    ),
                ),
                "admission_benefits": benefit_snapshot,
            }
        )
        area_count = len(
            {
                weight.area
                for discipline in canonical.disciplines
                for weight in discipline.area_weights
            }
        )
        normalize_logger.info(
            "stage=canonical_complete programs=%d disciplines=%d curricula=%d items=%d areas=%d",
            len(canonical.programs),
            len(canonical.disciplines),
            len(canonical.curricula),
            sum(len(curriculum.items) for curriculum in canonical.curricula),
            area_count,
        )
        normalize_logger.info("stage=events_complete events=%d", len(canonical.events))
        normalize_logger.info(
            "stage=campus_complete points=%d", len(canonical.campus_points)
        )
        normalize_logger.info(
            "stage=orders_complete documents=%d records=%d gaps=%d numeric=%d bvi=%d",
            len(captured.by_kind("bmstu_admission_orders_document")),
            len(order_records),
            len(order_gaps),
            sum(
                1
                for record in order_records
                for score in record.passing_scores
                if score.status == "numeric"
            ),
            sum(
                1
                for record in order_records
                for score in record.passing_scores
                if score.status == "bvi"
            ),
        )
        return raw, canonical

    def parse_sources(
        self,
        mode: str = "fixture",
        fixture_dir: Path | None = None,
        event_fixture_dir: Path | None = None,
        campus_fixture_dir: Path | None = None,
        program_codes: Sequence[str] | None = None,
        admission_benefits_fixture_dir: Path | None = None,
        admission_year: int = 2026,
        source_run_id: IngestRunId | None = None,
        include_admission_benefits: bool = False,
    ) -> tuple[RawTracerBundle, CanonicalSnapshot]:
        captured = self.capture(
            mode=mode,
            fixture_dir=fixture_dir,
            event_fixture_dir=event_fixture_dir,
            campus_fixture_dir=campus_fixture_dir,
            admission_benefits_fixture_dir=admission_benefits_fixture_dir,
            admission_year=admission_year,
            include_admission_benefits=include_admission_benefits,
        )
        return self.parse(
            captured,
            program_codes=program_codes,
            source_run_id=source_run_id,
            admission_year=admission_year,
        )


_ADMISSION_DOCUMENT_TITLES = {
    "appendix_5_1": "Приложение 5.1. Особое право приёма БВИ, 2026",
    "appendix_5_2": "Приложение 5.2. Особое право приёма БВИ, 2026",
    "appendix_5_3": "Приложение 5.3. Соответствие олимпиад для 100 баллов, 2026",
    "appendix_5_4": "Приложение 5.4. Соответствие для Всероссийской олимпиады школьников, 2026",
    "appendix_5_5": "Приложение 5.5. Соответствие для международной олимпиады, 2026",
    "appendix_6": "Приложение 6. Индивидуальные достижения, 2026",
    "appendix_7": "Приложение 7. Индивидуальные достижения магистратуры, 2026",
}


def _parse_admission_benefits(
    captured: CapturedSources,
    *,
    source_run_id: IngestRunId,
    university_id: str,
    known_direction_codes: frozenset[str],
    direction_index: dict[str, str],
    admission_year: int,
) -> tuple[
    tuple[RawAdmissionBenefitRecord, ...],
    tuple[AdmissionBenefitParserDiagnostic, ...],
    AdmissionBenefitsSnapshot | None,
]:
    snapshots = tuple(
        snapshot
        for snapshot in captured.snapshots
        if snapshot.source_kind.startswith("bmstu_admission_document:")
    )
    index_snapshots = captured.by_kind(INDEX_SOURCE_KIND)
    profile_snapshots = tuple(
        snapshot
        for snapshot in captured.snapshots
        if snapshot.source_kind.startswith("bmstu_olympiad_profile:")
    )
    relevant_gaps = tuple(
        gap
        for gap in captured.source_gaps
        if gap.entity_key.startswith(
            (
                "bmstu_admission_document_index:",
                "bmstu_admission_document:",
                "bmstu_olympiad_profile:",
            )
        )
    )
    if (
        not snapshots
        and not index_snapshots
        and not profile_snapshots
        and not relevant_gaps
    ):
        return (), (), None

    index_snapshot = index_snapshots[0] if len(index_snapshots) == 1 else None
    manifest = None
    if index_snapshot is not None:
        try:
            manifest = discover_document_manifest(
                index_snapshot.body, admission_year=admission_year
            )
        except ContractError:
            normalize_logger.warning(
                "bmstu_admission_benefit_manifest_invalid university_id=%s year=%d run_id=%s",
                university_id,
                admission_year,
                source_run_id,
            )
    expected_manifest = BmstuAdmissionSourceManifest(
        index_url=cast(HttpUrl, BMSTU_ADMISSION_DOCUMENTS_INDEX_URL),
        admission_year=admission_year,
    )
    required_kinds = expected_manifest.required_kinds
    discovered_kinds = (
        {document.kind for document in manifest.discovered}
        if manifest is not None
        else set()
    )
    captured_document_kinds = {
        BmstuAdmissionDocumentKind(snapshot.source_kind.rsplit(":", 1)[-1])
        for snapshot in snapshots
        if snapshot.source_kind.rsplit(":", 1)[-1]
        in {kind.value for kind in BmstuAdmissionDocumentKind}
    }
    coverage_snapshots = (
        *snapshots,
        *profile_snapshots,
        *((index_snapshot,) if index_snapshot else ()),
    )

    parser = BmstuAdmissionBenefitsParser()
    benefit_records: list[RawAdmissionBenefitRecord] = []
    individual_records: list[RawIndividualAchievementRecord] = []
    diagnostics: list[AdmissionBenefitParserDiagnostic] = []
    profile_sources = []
    for snapshot in captured.snapshots:
        if not snapshot.source_kind.startswith("bmstu_olympiad_profile:"):
            continue
        profile_result: BmstuOlympiadProfileParseResult = parse_olympiad_profile_source(
            snapshot,
            source_run_id=source_run_id,
            admission_year=admission_year,
        )
        diagnostics.extend(profile_result.diagnostics)
        if profile_result.source is not None:
            profile_sources.append(
                OlympiadProfileSourceEnrichment(source=profile_result.source)
            )
    rules_snapshot = next(
        (snapshot for snapshot in snapshots if snapshot.source_kind.rsplit(":", 1)[-1] == "rules"),
        None,
    )
    rule_policy = parse_admission_rule_policy(rules_snapshot) if rules_snapshot is not None else None
    rule_policy_provenance = (
        _admission_rules_provenance(
            rules_snapshot,
            source_run_id=source_run_id,
            admission_year=admission_year,
            page=rule_policy.validity_locator.page if rule_policy and rule_policy.validity_locator else None,
        )
        if rules_snapshot is not None and rule_policy is not None
        else None
    )
    for snapshot in snapshots:
        document_kind = snapshot.source_kind.rsplit(":", 1)[-1]
        if document_kind == "rules":
            continue
        document = RawAdmissionBenefitDocument(
            document_kind=document_kind,
            document_title=_ADMISSION_DOCUMENT_TITLES.get(
                document_kind, f"BMSTU admission document {admission_year}"
            ),
            admission_year=admission_year,
            source_url=snapshot.requested_url,
            source_snapshot_hash=snapshot.content_sha256,
            source_run_id=source_run_id,
            captured_at=snapshot.captured_at,
            locator=SourceLocator(source_url=snapshot.requested_url),
            parser_version=ADMISSION_BENEFITS_PARSER_VERSION,
        )
        tables = _benefit_fixture_tables(snapshot)
        document_pages = _benefit_fixture_document_pages(snapshot)
        if tables is None and is_pdf(
            snapshot.body, snapshot.content_type, str(snapshot.requested_url)
        ):
            try:
                tables = tuple(extract_pdf_tables(snapshot.body))
                document_pages = tuple(
                    enumerate(extract_pdf_pages_text(snapshot.body), start=1)
                )
            except (OSError, RuntimeError, ValueError) as exc:
                diagnostics.append(
                    AdmissionBenefitParserDiagnostic(
                        code="pdf_table_extract_failed",
                        stage="pdf",
                        message="PDF table extraction failed; source remains available for review",
                        severity="warning",
                        locator=document.locator,
                    )
                )
                parse_logger.warning(
                    "bmstu_admission_benefit_table_extract_failed kind=%s error_type=%s",
                    document_kind,
                    type(exc).__name__,
                )
                tables = ()
        if document_kind in {"appendix_6", "appendix_7"}:
            parsed_achievements, parser_diagnostics = (
                parse_individual_achievement_tables(
                    document,
                    tables or (),
                    document_pages=document_pages or (),
                )
            )
            individual_records.extend(parsed_achievements)
        elif document_kind in {"appendix_5_4", "appendix_5_5"}:
            parsed_benefits, parser_diagnostics = parse_special_olympiad_tables(
                document, tables or ()
            )
            benefit_records.extend(parsed_benefits)
        elif document_kind in {"appendix_8_1", "appendix_8_3"}:
            # These are admission-place/targeted-quota projections, not
            # olympiad benefit tables.  Keep the captured source in the
            # snapshot, but do not manufacture legal benefit rows from it.
            parsed_benefits = ()
            parser_diagnostics = (
                AdmissionBenefitParserDiagnostic(
                    code="quota_document_pending_projection",
                    stage="document_dispatch",
                    message="Appendix 8.x is captured but belongs to the admissions quota projection, not admission-benefit rules",
                    severity="info",
                    locator=document.locator,
                ),
            )
        else:
            parsed_benefits, parser_diagnostics = parser.parse_snapshot(
                snapshot,
                document_kind=document_kind,
                document_title=document.document_title,
                source_run_id=source_run_id,
                tables=tables,
            )
            benefit_records.extend(parsed_benefits)
        diagnostics.extend(parser_diagnostics)

    olympiad_result = normalize_olympiad_benefits(
        tuple(benefit_records),
        university_id=university_id,
        known_direction_codes=known_direction_codes,
        policy_version=BenefitPolicyVersion(
            schema_version=ADMISSION_BENEFITS_SCHEMA_VERSION,
            parser_version=ADMISSION_BENEFITS_PARSER_VERSION,
            policy_version=ADMISSION_BENEFITS_POLICY_VERSION,
        ),
        olympiad_result_max_age_years=(
            rule_policy.olympiad_result_max_age_years
            if rule_policy is not None
            else None
        ),
        olympiad_result_validity_text=(
            rule_policy.olympiad_result_validity_text
            if rule_policy is not None
            else None
        ),
        olympiad_confirmation_min_score=(
            rule_policy.olympiad_confirmation_min_score
            if rule_policy is not None
            else None
        ),
        olympiad_confirmation_text=(
            rule_policy.olympiad_confirmation_text if rule_policy is not None else None
        ),
        olympiad_confirmation_thresholds=(
            rule_policy.confirmation_thresholds if rule_policy is not None else ()
        ),
        rule_policy_provenance=rule_policy_provenance,
        validity_locator=(rule_policy.validity_locator if rule_policy is not None else None),
        profile_sources=tuple(profile_sources),
        direction_index=direction_index,
    )
    achievement_result = (
        normalize_individual_achievements(
            tuple(individual_records),
            university_id=university_id,
            policy_version=BenefitPolicyVersion(
                schema_version=ADMISSION_BENEFITS_SCHEMA_VERSION,
                parser_version=ADMISSION_BENEFITS_PARSER_VERSION,
                policy_version=ADMISSION_BENEFITS_POLICY_VERSION,
            ),
            documents_discovered=len(snapshots),
            documents_captured=len(snapshots),
        )
        if individual_records
        else None
    )
    diagnostics.extend(olympiad_result.diagnostics)
    if achievement_result is not None:
        diagnostics.extend(achievement_result.diagnostics)
    all_records = (*benefit_records, *individual_records)
    if not all_records:
        parse_logger.warning(
            "bmstu_admission_benefits_no_rows snapshots=%d", len(snapshots)
        )
    coverage = build_coverage(
        documents_discovered=len(manifest.discovered)
        if manifest is not None
        else len(snapshots),
        documents_selected=len(manifest.selected)
        if manifest is not None
        else len(snapshots),
        documents_captured=len(snapshots),
        documents_parsed=len(snapshots),
        required_documents_expected=len(required_kinds),
        required_documents_discovered=max(
            len(required_kinds & discovered_kinds),
            len(required_kinds & captured_document_kinds),
        ),
        required_documents_captured=len(required_kinds & captured_document_kinds),
        manifest_hash=index_snapshot.content_sha256 if index_snapshot else None,
        source_hashes=tuple(snapshot.content_sha256 for snapshot in coverage_snapshots),
        source_gaps=tuple(source_gap_reference(gap) for gap in relevant_gaps),
        records=all_records,
        normalized_count=len(olympiad_result.rules)
        + (
            len(achievement_result.policy.rules)
            if achievement_result and achievement_result.policy
            else 0
        ),
        resolved_targets=sum(
            1
            for rule in olympiad_result.rules
            for target in rule.scope.targets
            if target.resolution.value == "resolved"
        ),
        unresolved_targets=olympiad_result.unresolved_targets,
        conflicts=len(achievement_result.conflicts) if achievement_result else 0,
        review_required_rows=sum(
            1
            for item in diagnostics
            if item.severity in {"warning", "ambiguous", "error"}
        ),
    )
    source_attributions = tuple(
        SourceAttribution(
            kind=SourceKind.BMSTU_ADMISSION_INDIVIDUAL_ACHIEVEMENTS
            if snapshot.source_kind.rsplit(":", 1)[-1] in {"appendix_6", "appendix_7"}
            else SourceKind.BMSTU_ADMISSION_BENEFITS,
            url=snapshot.requested_url,
            captured_at=snapshot.captured_at,
            content_sha256=snapshot.content_sha256,
            university_id=university_id,
            run_id=source_run_id,
        )
        for snapshot in coverage_snapshots
    )
    result = AdmissionBenefitsSnapshot(
        university_id=university_id,
        admission_year=admission_year,
        sources=source_attributions,
        olympiads=olympiad_result.olympiads,
        olympiad_profiles=olympiad_result.profiles,
        benefit_rules=olympiad_result.rules,
        individual_achievement_policy=achievement_result.policy
        if achievement_result
        else None,
        coverage=coverage,
        source_gaps=tuple(source_gap_reference(gap) for gap in relevant_gaps),
        diagnostics=tuple(diagnostics),
    )
    normalize_logger.info(
        "bmstu_admission_benefits_normalized year=%d snapshots=%d raw_rows=%d rules=%d achievement_rules=%d diagnostics=%d coverage=%s",
        admission_year,
        len(snapshots),
        len(all_records),
        len(result.benefit_rules),
        len(result.individual_achievement_policy.rules)
        if result.individual_achievement_policy
        else 0,
        len(result.diagnostics),
        result.coverage.status,
    )
    return tuple(all_records), tuple(diagnostics), result


def _benefit_fixture_tables(
    snapshot: RawSourceSnapshot,
) -> tuple[dict[str, object], ...] | None:
    """Read minimized official extracts used by parser/integration tests."""

    try:
        payload = json.loads(snapshot.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    raw_tables = payload.get("tables")
    if isinstance(raw_tables, list):
        tables: list[dict[str, object]] = []
        for index, raw_table in enumerate(raw_tables, start=1):
            if not isinstance(raw_table, dict) or not isinstance(
                raw_table.get("rows"), list
            ):
                return None
            table = dict(raw_table)
            table.setdefault("page", 1)
            table.setdefault("table", index)
            tables.append(table)
        return tuple(tables) or None
    if not isinstance(payload.get("rows"), list):
        return None
    locator = str(payload.get("locator", ""))
    page = next(
        (
            int(part.split("=", 1)[1])
            for part in locator.split(";")
            if part.startswith("page=") and part.split("=", 1)[1].isdigit()
        ),
        1,
    )
    table_number = next(
        (
            int(part.split("=", 1)[1])
            for part in locator.split(";")
            if part.startswith("table=") and part.split("=", 1)[1].isdigit()
        ),
        1,
    )
    rows = payload["rows"]
    if not all(isinstance(row, list) for row in rows):
        return None
    document_kind = snapshot.source_kind.rsplit(":", 1)[-1]
    if document_kind == "appendix_5_1":
        rows = [
            ["№", "Олимпиада", "Профиль", "Победитель", "Призер", "Направления"],
            *rows,
        ]
    elif document_kind == "appendix_5_3":
        column_count = max((len(row) for row in rows), default=0)
        if column_count >= 8:
            rows = [
                [
                    "№",
                    "Олимпиада",
                    "Профиль",
                    "Общеобразовательные предметы или направления подготовки",
                    "Уровень",
                    "Профильные общеобразовательные предметы для предоставления особого права на 100 баллов при подтверждении олимпиады 75 баллами по ЕГЭ",
                    "Победитель",
                    "Призер",
                ],
                *rows,
            ]
        else:
            rows = [["№", "Олимпиада", "Профиль", "Победитель", "Призер"], *rows]
    if payload.get("confirmation_text"):
        confirmation_text = str(payload["confirmation_text"])
        rows[0] = [*rows[0], f"Подтверждение: {confirmation_text}"]
        rows[1:] = [row + [confirmation_text] for row in rows[1:]]
    row_numbers = payload.get("row_numbers")
    table_payload: dict[str, object] = {
        "page": page,
        "table": table_number,
        "rows": rows,
    }
    if isinstance(row_numbers, list) and all(
        isinstance(value, int) for value in row_numbers
    ):
        table_payload["row_numbers"] = row_numbers
    row_pages = payload.get("row_pages")
    if isinstance(row_pages, list) and all(
        isinstance(value, int) for value in row_pages
    ):
        table_payload["row_pages"] = row_pages
    return (table_payload,)


def _benefit_fixture_document_pages(
    snapshot: RawSourceSnapshot,
) -> tuple[tuple[int, str], ...]:
    try:
        payload = json.loads(snapshot.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return ()
    if not isinstance(payload, dict) or not isinstance(payload.get("text_layer_pages"), list):
        return ()
    pages = tuple(
        (item["page"], item["text"])
        for item in payload["text_layer_pages"]
        if isinstance(item, dict)
        and isinstance(item.get("page"), int)
        and item["page"] >= 1
        and isinstance(item.get("text"), str)
        and item["text"].strip()
    )
    return pages


def _derived_benefit_run_id(captured: CapturedSources) -> IngestRunId:
    seed = "|".join(sorted(snapshot.content_sha256 for snapshot in captured.snapshots))
    return f"ingest:{sha256(seed.encode('utf-8')).hexdigest()[:32]}"


def _admission_rules_provenance(
    snapshot: RawSourceSnapshot,
    *,
    source_run_id: IngestRunId,
    admission_year: int,
    page: int | None,
) -> BenefitProvenance:
    locator = f"page={page};section=1.11-1.12" if page is not None else "section=1.11-1.12"
    attribution = SourceAttribution(
        kind=SourceKind.BMSTU_ADMISSION_RULES,
        url=snapshot.requested_url,
        captured_at=snapshot.captured_at,
        content_sha256=snapshot.content_sha256,
        locator=locator,
        university_id="university:bmstu",
        run_id=source_run_id,
    )
    return BenefitProvenance(
        source=attribution,
        source_snapshot_hash=snapshot.content_sha256,
        source_run_id=source_run_id,
        admission_year=admission_year,
        document_title=f"Правила приёма в МГТУ им. Н.Э. Баумана в {admission_year} году",
        document_kind="rules",
        page=page,
        section="1.11–1.12",
        parser_version=ADMISSION_BENEFITS_PARSER_VERSION,
    )


def _canonicalize_admission_code(
    record: RawAdmissionRecord, programs: Sequence[RawProgramRecord]
) -> RawAdmissionRecord:
    source_code = record.program_code
    source_name = record.program_name
    source_directions = extract_direction_codes(source_code)
    canonical = (
        source_directions[0]
        if record.scope == "direction" and len(source_directions) == 1
        else map_source_program_code(
            source_code,
            source_name,
            programs,
        )
    )
    return record.model_copy(
        update={"program_code": canonical, "source_program_code": source_code}
    )


def _canonicalize_admission_records(
    records: Sequence[RawAdmissionRecord],
    programs: Sequence[RawProgramRecord],
) -> tuple[tuple[RawAdmissionRecord, ...], tuple[RawSourceGap, ...]]:
    """Canonicalize source rows and quarantine identities outside this catalog.

    BMSTU publishes historical and cross-catalog admission rows together with
    the current detail payload.  An unknown direction/profile must not be
    projected to a current program, but it is still useful source evidence.
    Ambiguous mappings continue to raise from ``_canonicalize_admission_code``
    so a parser change cannot silently guess a target.
    """

    known_program_codes = {_canonical_code(program.code) for program in programs}
    known_direction_codes = {
        direction
        for program in programs
        for direction in (
            extract_direction_codes(program.direction_code)
            or extract_direction_codes(program.code)
            or (_canonical_code(program.direction_code),)
        )
    }
    accepted: list[RawAdmissionRecord] = []
    gaps: list[RawSourceGap] = []
    for source_record in records:
        record = _canonicalize_admission_code(source_record, programs)
        code = _canonical_code(record.program_code)
        if record.scope == "direction":
            known = code in known_direction_codes or any(
                program_code.startswith(f"{code}-")
                for program_code in known_program_codes
            )
        else:
            known = code in known_program_codes
        if known:
            accepted.append(record)
            continue
        gap = _admission_identity_gap(record)
        gaps.append(gap)
        parse_logger.warning(
            "admission_source_gap reason=%s program_code=%s source_url=%s locator=%s",
            gap.reason,
            record.program_code,
            record.source_url,
            record.locator.field or record.locator.page or record.locator.row,
        )
    return tuple(accepted), tuple(gaps)


def _admission_identity_gap(record: RawAdmissionRecord) -> RawSourceGap:
    stable = "|".join(
        (
            record.id,
            record.program_code,
            str(record.admission_year),
            str(record.source_url),
            record.locator.field or "",
        )
    )
    return RawSourceGap(
        id=f"source-gap:bmstu-admission-identity:{sha256(stable.encode('utf-8')).hexdigest()}",
        entity_type="admission",
        entity_key=f"{record.program_code}:{record.admission_year}:{record.id}",
        reason="admission-program-identity-unknown",
        source_url=record.source_url,
        locator=record.locator,
    )


def _parse_order_admissions(
    captured: CapturedSources,
    programs: Sequence[RawProgramRecord],
) -> tuple[tuple[RawAdmissionRecord, ...], tuple[RawSourceGap, ...]]:
    order_snapshots = captured.by_kind("bmstu_admission_orders_document")
    if not order_snapshots:
        return (), ()
    manifest_snapshots = captured.by_kind("bmstu_admission_orders_index")
    if len(manifest_snapshots) != 1:
        raise ValueError(
            "BMSTU order documents require exactly one orders manifest snapshot"
        )
    entries = parse_orders_manifest(
        manifest_snapshots[0].body, str(manifest_snapshots[0].requested_url)
    )
    entries_by_url = {entry.requested_url: entry for entry in entries}
    direction_codes = tuple(
        sorted(
            {
                direction
                for program in programs
                for direction in (
                    extract_direction_codes(program.direction_code)
                    or (
                        _canonical_code(program.direction_code)
                        or _canonical_code(program.code)
                        or program.code,
                    )
                )
            }
        )
    )
    records: list[RawAdmissionRecord] = []
    gaps: list[RawSourceGap] = []
    for snapshot in order_snapshots:
        requested_url = str(snapshot.requested_url)
        entry = entries_by_url.get(requested_url)
        if entry is None:
            gaps.append(_order_gap(snapshot, "manifest_entry_missing", None, None))
            continue
        pages = iter_pdf_pages(snapshot.body)
        metadata = classify_order_document(entry, pages)
        if not metadata.supported_catalog:
            select_logger.info(
                "[FIX:source-gap] orders_document_unsupported url=%s kind=%s",
                requested_url,
                metadata.document_kind.value,
            )
            gaps.append(
                _order_gap(snapshot, "unsupported_document_kind", metadata, None)
            )
            continue
        if metadata.admission_year is None:
            select_logger.warning(
                "[FIX:source-gap] orders_document_missing_year url=%s", requested_url
            )
            gaps.append(_order_gap(snapshot, "admission_year_unknown", metadata, None))
            continue
        result = parse_admission_order_document(snapshot.body, metadata)
        if result.failed:
            gaps.append(
                _order_gap(snapshot, "order_document_parse_failed", metadata, None)
            )
            continue
        for warning in result.warnings:
            if warning.startswith("competition_heading_unknown"):
                gaps.append(_order_gap(snapshot, warning, metadata, None))
        present_directions = {
            observation.direction_code for observation in result.observations
        }
        for direction_code in direction_codes:
            if direction_code not in present_directions:
                gaps.append(
                    _order_gap(
                        snapshot,
                        "direction_section_not_published",
                        metadata,
                        direction_code,
                    )
                )
        unknown_directions = sorted(present_directions - set(direction_codes))
        for unknown_direction in unknown_directions:
            gaps.append(
                _order_gap(
                    snapshot,
                    "order_direction_not_in_catalog",
                    metadata,
                    unknown_direction,
                )
            )
        for observation in result.observations:
            if observation.direction_code not in direction_codes:
                continue
            locator = SourceLocator(
                source_url=snapshot.requested_url,
                page=observation.page,
                row=observation.row,
                field=f"competition={observation.competition_type.value};status={observation.status}",
            )
            score = RawAdmissionPassingScore(
                score_type=observation.score_type,
                competition_type=observation.competition_type.value,
                status=observation.status,
                score=observation.score,
            )
            stable = "|".join(
                (
                    observation.direction_code,
                    str(observation.admission_year),
                    observation.funding_type,
                    observation.competition_type.value,
                    observation.status,
                    str(observation.score),
                )
            )
            records.append(
                RawAdmissionRecord(
                    id=f"admission-order:{sha256(stable.encode('utf-8')).hexdigest()}",
                    program_code=observation.direction_code,
                    admission_year=observation.admission_year,
                    study_form=observation.study_form,
                    funding_type=observation.funding_type,
                    scope="direction",
                    passing_scores=(score,),
                    source_kind="bmstu_admission_orders_document",
                    source_url=snapshot.requested_url,
                    locator=locator,
                    source_program_code=observation.direction_code,
                )
            )
    parse_logger.info(
        "orders_projection_complete documents=%d records=%d gaps=%d directions=%d",
        len(order_snapshots),
        len(records),
        len(gaps),
        len(direction_codes),
    )
    return tuple(records), tuple(gaps)


def _order_gap(
    snapshot: RawSourceSnapshot,
    reason: str,
    metadata: object | None,
    direction_code: str | None,
) -> RawSourceGap:
    year = getattr(metadata, "admission_year", None)
    funding = getattr(getattr(metadata, "funding", None), "value", "unknown")
    stage = getattr(getattr(metadata, "stage", None), "value", "unknown")
    key = "|".join(
        (
            str(snapshot.requested_url),
            str(year or "unknown"),
            direction_code or "document",
            funding,
            stage,
            reason,
        )
    )
    field = f"funding={funding};stage={stage}"
    gap = RawSourceGap(
        id=f"source-gap:bmstu-admission-order:{sha256(key.encode('utf-8')).hexdigest()}",
        entity_type="admission_order",
        entity_key=f"{direction_code or 'document'}:{year or 'unknown'}:{funding}:{stage}",
        reason=reason[:512],
        source_url=snapshot.requested_url,
        locator=SourceLocator(source_url=snapshot.requested_url, field=field),
    )
    parse_logger.warning(
        "orders_source_gap reason=%s direction=%s year=%s funding=%s stage=%s source_url=%s",
        gap.reason,
        direction_code or "document",
        year or "unknown",
        funding,
        stage,
        snapshot.requested_url,
    )
    return gap


def _fixture_documented_codes(captured: CapturedSources) -> tuple[str, ...] | None:
    """Scope only the historical fixture when its HTML detail has extra profiles."""

    detail_snapshots = captured.by_kind("bmstu_major_detail")
    if not detail_snapshots or any(
        "api.www.bmstu.ru/majors/" in str(snapshot.requested_url)
        for snapshot in detail_snapshots
    ):
        return None
    document_urls = {
        str(snapshot.requested_url)
        for snapshot in captured.by_kind("bmstu_curriculum_document")
    }
    if not document_urls:
        return None
    codes = tuple(
        _canonical_code(code)
        for snapshot in detail_snapshots
        for code, _, plan in _detail_plan_records(snapshot.body)
        if plan in document_urls
    )
    return tuple(dict.fromkeys(codes)) or None


def _canonical_code(value: str) -> str:
    return value.replace("–", "-").replace("—", "-").replace("/", "-").replace(" ", "")


__all__ = ["BmstuUniversityAdapter"]
