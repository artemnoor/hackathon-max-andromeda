"""Deterministic semantic classification with a replaceable policy seam."""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal

from andromeda.shared.contracts.errors import ContractError, ErrorCode
from andromeda.shared.contracts.provenance import GapSeverity, SourceGapReference
from andromeda.shared.contracts.versions import (
    SEMANTIC_CLASSIFIER_VERSION,
    SEMANTIC_TAXONOMY_VERSION,
)

from ..contracts.inputs import SemanticClassificationInput
from ..contracts.review_artifacts import ReviewedSemanticArtifact, SemanticProposalState
from ..contracts.public import (
    CurriculumItemSemanticFeature,
    DisciplineSemanticDefault,
    SemanticClassificationEvidence,
    SemanticClassificationMethod,
    SemanticClassificationResult,
    SemanticFeatureValue,
    SemanticReviewStatus,
    SemanticValueStatus,
)
from ..domain import DEFAULT_SEMANTIC_FEATURES
from .rules import DEFAULT_SEMANTIC_RULES, SemanticRule

logger = logging.getLogger("andromeda.semantic.classifier")


class RuleBasedSemanticClassifier:
    """Classify names into independent semantic signals using audited rules."""

    def __init__(
        self,
        *,
        rules: Iterable[SemanticRule] = DEFAULT_SEMANTIC_RULES,
        aliases: Mapping[str, str] | None = None,
        taxonomy_version: str = SEMANTIC_TAXONOMY_VERSION,
        classifier_version: str = SEMANTIC_CLASSIFIER_VERSION,
    ) -> None:
        self._taxonomy_version = taxonomy_version
        self._classifier_version = classifier_version
        self._features_by_code = {feature.code: feature for feature in DEFAULT_SEMANTIC_FEATURES}
        validated_rules = tuple(rules)
        rule_ids: set[str] = set()
        for rule in validated_rules:
            if rule.rule_id in rule_ids:
                raise ValueError(f"duplicate semantic rule: {rule.rule_id}")
            if rule.feature_code not in self._features_by_code:
                raise ValueError(f"unsupported semantic feature code: {rule.feature_code}")
            if not Decimal("0") <= rule.value <= Decimal("1"):
                raise ValueError(f"semantic rule value out of bounds: {rule.rule_id}")
            if not Decimal("0") <= rule.confidence <= Decimal("1"):
                raise ValueError(f"semantic rule confidence out of bounds: {rule.rule_id}")
            if not rule.keywords or any(not keyword.strip() for keyword in rule.keywords):
                raise ValueError(f"semantic rule has no usable keywords: {rule.rule_id}")
            rule_ids.add(rule.rule_id)
        self._rules = validated_rules
        self._aliases = {
            _normalize_name(alias): _normalize_name(target)
            for alias, target in (aliases or {}).items()
        }

    @property
    def semantic_version(self) -> str:
        return self._taxonomy_version

    @property
    def classifier_version(self) -> str:
        return self._classifier_version

    def classify(self, input: SemanticClassificationInput) -> SemanticClassificationResult:
        if input.semantic_version is not None and input.semantic_version != self._taxonomy_version:
            raise ContractError(ErrorCode.CONTRACT_ERROR, "Unsupported semantic taxonomy version")
        normalized_name = _normalize_name(input.normalized_name)
        alias_target = self._aliases.get(normalized_name)
        source_text = _normalize_name(input.source_text) if input.source_text else ""
        matching_text = " ".join(value for value in (normalized_name, alias_target, source_text) if value)
        matches: dict[str, list[tuple[SemanticRule, tuple[str, ...]]]] = {}
        for rule in self._rules:
            terms = tuple(keyword for keyword in rule.keywords if keyword in matching_text)
            if terms:
                matches.setdefault(rule.feature_code, []).append((rule, terms))

        created_at = input.provenance[0].captured_at if input.provenance else datetime(1970, 1, 1, tzinfo=UTC)
        values: list[SemanticFeatureValue] = []
        for feature in DEFAULT_SEMANTIC_FEATURES:
            feature_matches = matches.get(feature.code, [])
            if not feature_matches:
                values.append(
                    SemanticFeatureValue(
                        feature_id=feature.id,
                        value=None,
                        status=SemanticValueStatus.UNKNOWN,
                        confidence=Decimal("0"),
                        classification_method=SemanticClassificationMethod.RULE,
                        review_status=SemanticReviewStatus.NEEDS_REVIEW,
                        classifier_version=self._classifier_version,
                        semantic_version=self._taxonomy_version,
                        source_hash=input.source_hash,
                        source_run_id=input.source_run_id,
                        created_at=created_at,
                        provenance=input.provenance,
                    )
                )
                continue
            selected = max(feature_matches, key=lambda match: (match[0].value, match[0].confidence, match[0].rule_id))
            evidence = tuple(
                SemanticClassificationEvidence(
                    feature_id=feature.id,
                    rule_id=rule.rule_id,
                    matched_terms=terms,
                    rationale=rule.rationale,
                )
                for rule, terms in feature_matches
            )
            values.append(
                SemanticFeatureValue(
                    feature_id=feature.id,
                    value=selected[0].value,
                    status=SemanticValueStatus.AVAILABLE,
                    confidence=selected[0].confidence,
                    classification_method=SemanticClassificationMethod.RULE,
                    review_status=_review_status(selected[0].confidence),
                    classifier_version=self._classifier_version,
                    semantic_version=self._taxonomy_version,
                    source_hash=input.source_hash,
                    source_run_id=input.source_run_id,
                    created_at=created_at,
                    evidence=evidence,
                    provenance=input.provenance,
                )
            )

        matched_count = len(matches)
        logger.info(
            "semantic_classification_completed discipline_id=%s item_id=%s matched_features=%d method_counts=rule:%d confidence_bucket=%s taxonomy_version=%s classifier_version=%s",
            input.discipline_id,
            input.curriculum_item_id,
            matched_count,
            matched_count,
            _confidence_bucket(values),
            self._taxonomy_version,
            self._classifier_version,
        )
        gaps = () if matched_count else (_insufficient_evidence_gap(input),)
        return SemanticClassificationResult(
            discipline_id=input.discipline_id,
            curriculum_item_id=input.curriculum_item_id,
            values=tuple(values),
            source_gaps=gaps,
        )

    @staticmethod
    def merge_with_discipline_defaults(
        defaults: Iterable[DisciplineSemanticDefault],
        item_result: SemanticClassificationResult,
        *,
        allow_inheritance: bool,
    ) -> tuple[CurriculumItemSemanticFeature, ...]:
        """Apply item evidence over defaults without coercing unknown to zero."""

        if item_result.curriculum_item_id is None:
            raise ValueError("item result is required to merge discipline defaults")
        default_by_feature = {item.feature.feature_id: item.feature for item in defaults}
        result: list[CurriculumItemSemanticFeature] = []
        for value in item_result.values:
            if value.status is SemanticValueStatus.UNKNOWN and value.feature_id in default_by_feature and allow_inheritance:
                inherited = default_by_feature[value.feature_id].model_copy(
                    update={
                        "classification_method": SemanticClassificationMethod.INHERITED,
                        # The semantic value comes from the discipline default, but
                        # audit identity belongs to this curriculum item.  Keeping
                        # the item's source hash is what makes changed-only refresh
                        # safe when two items share one discipline.
                        "source_hash": value.source_hash,
                        "source_run_id": value.source_run_id,
                        "provenance": value.provenance,
                        "created_at": value.created_at,
                    }
                )
                result.append(
                    CurriculumItemSemanticFeature(
                        curriculum_item_id=item_result.curriculum_item_id,
                        feature=inherited,
                        overrides_discipline_default=False,
                    )
                )
                continue
            result.append(
                CurriculumItemSemanticFeature(
                    curriculum_item_id=item_result.curriculum_item_id,
                    feature=value,
                    overrides_discipline_default=value.status is SemanticValueStatus.AVAILABLE and value.feature_id in default_by_feature,
                )
            )
        return tuple(result)


class ReviewedMappingSemanticClassifier:
    """Apply only accepted, source-matched review mappings over rule output."""

    def __init__(self, base: RuleBasedSemanticClassifier, artifact: ReviewedSemanticArtifact) -> None:
        if artifact.semantic_version != base.semantic_version:
            raise ValueError("reviewed semantic artifact taxonomy version is stale")
        self._base = base
        self._artifact = artifact

    @property
    def semantic_version(self) -> str:
        return self._artifact.semantic_version

    @property
    def classifier_version(self) -> str:
        return self._artifact.classifier_version

    def classify(self, input: SemanticClassificationInput) -> SemanticClassificationResult:
        result = self._base.classify(input)
        candidates = tuple(
            proposal
            for proposal in self._artifact.mappings
            if proposal.state is SemanticProposalState.ACCEPTED
            and proposal.source_hash == input.source_hash
            and (
                proposal.curriculum_item_id == input.curriculum_item_id
                if input.curriculum_item_id is not None
                else proposal.discipline_id == input.discipline_id
            )
        )
        if not candidates:
            return result
        by_feature = {proposal.feature_id: proposal.feature for proposal in candidates}
        values = tuple(by_feature.get(value.feature_id, value) for value in result.values)
        return result.model_copy(update={"values": values})


def merge_semantic_values(
    defaults: Iterable[DisciplineSemanticDefault],
    item_result: SemanticClassificationResult,
    *,
    allow_inheritance: bool,
) -> tuple[CurriculumItemSemanticFeature, ...]:
    return RuleBasedSemanticClassifier.merge_with_discipline_defaults(
        defaults,
        item_result,
        allow_inheritance=allow_inheritance,
    )


def _insufficient_evidence_gap(input: SemanticClassificationInput) -> SourceGapReference:
    source_url = input.provenance[0].url if input.provenance else None
    return SourceGapReference(
        code="semantic-classification-insufficient",
        severity=GapSeverity.DEGRADABLE,
        message="No deterministic semantic rule matched the discipline evidence.",
        source_url=source_url,
        field="semantic_features",
        record_key=input.curriculum_item_id or input.discipline_id,
        can_continue=True,
    )


def _review_status(confidence: Decimal) -> SemanticReviewStatus:
    # These buckets are frozen from semantic corpus v1.  They are intentionally
    # conservative: deterministic rules below 0.80 are review candidates, not
    # facts suitable for an unqualified user-facing aggregate.
    return SemanticReviewStatus.UNREVIEWED if confidence >= Decimal("0.80") else SemanticReviewStatus.NEEDS_REVIEW


def _confidence_bucket(values: Iterable[SemanticFeatureValue]) -> str:
    available = tuple(value.confidence for value in values if value.status is SemanticValueStatus.AVAILABLE)
    if not available:
        return "unresolved"
    minimum = min(available)
    if minimum >= Decimal("0.85"):
        return "automatic_high"
    return "automatic_low"


def _normalize_name(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value.replace("\xa0", " ")).casefold().split())
    normalized = normalized.replace("ё", "е")
    return re.sub(r"[‐‑‒–—―]", "-", normalized)


__all__ = ["ReviewedMappingSemanticClassifier", "RuleBasedSemanticClassifier", "merge_semantic_values"]
