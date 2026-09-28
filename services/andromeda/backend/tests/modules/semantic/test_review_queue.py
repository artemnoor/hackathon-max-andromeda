from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from andromeda.modules.semantic.contracts.public import (
    SemanticClassificationMethod,
    SemanticFeatureValue,
    SemanticReviewStatus,
    SemanticValueStatus,
)
from andromeda.modules.semantic.contracts.review import (
    SemanticReviewCandidate,
    SemanticReviewReason,
    build_review_queue,
)
from andromeda.modules.semantic.contracts.review_artifacts import SemanticReviewAction, SemanticProposalState
from andromeda.modules.semantic.domain import DEFAULT_SEMANTIC_FEATURES
from andromeda.modules.semantic.services.classifier import ReviewedMappingSemanticClassifier, RuleBasedSemanticClassifier
from andromeda.modules.semantic.services.review_workflow import SemanticReviewWorkflow
from andromeda.modules.semantic.contracts.inputs import SemanticClassificationInput


NOW = datetime(2026, 9, 22, tzinfo=UTC)
SOURCE_HASH = "a" * 64


def _value(*, confidence: str = "0.70", status: SemanticValueStatus = SemanticValueStatus.AVAILABLE) -> SemanticFeatureValue:
    feature = DEFAULT_SEMANTIC_FEATURES[0]
    return SemanticFeatureValue(
        feature_id=feature.id,
        value=Decimal("0.40") if status is SemanticValueStatus.AVAILABLE else None,
        status=status,
        confidence=Decimal(confidence),
        classification_method=SemanticClassificationMethod.RULE,
        review_status=SemanticReviewStatus.NEEDS_REVIEW,
        source_hash=SOURCE_HASH,
        semantic_version="semantic-taxonomy.v1",
        classifier_version="semantic-classifier.v1",
        created_at=NOW,
    )


def _candidate(value: SemanticFeatureValue) -> SemanticReviewCandidate:
    return SemanticReviewCandidate(
        discipline_id="discipline:aaaaaaaaaaaaaaaa",
        curriculum_item_id="curriculum-item:program:09.03.03-01:discipline:aaaaaaaaaaaaaaaa:1",
        discipline_name="Математический анализ",
        values=(value,),
        source_hash=SOURCE_HASH,
        semantic_version="semantic-taxonomy.v1",
        classifier_version="semantic-classifier.v1",
        created_at=NOW,
    )


def test_review_queue_is_stable_and_keeps_unavailable_as_missing() -> None:
    candidate = _candidate(_value(status=SemanticValueStatus.UNKNOWN))
    first = build_review_queue((candidate,))[0]
    second = build_review_queue((candidate,))[0]

    assert first.queue_id == second.queue_id
    assert SemanticReviewReason.MISSING_COVERAGE in first.reasons
    assert first.values[0].value is None
    assert build_review_queue((candidate,), reviewed_queue_ids=frozenset({first.queue_id})) == ()


def test_review_workflow_requires_human_acceptance_and_rejects_stale_source() -> None:
    queue_item = build_review_queue((_candidate(_value()),))[0]
    workflow = SemanticReviewWorkflow()
    proposal = workflow.propose(
        queue_item,
        feature_id=queue_item.values[0].feature_id,
        feature=queue_item.values[0],
        tool_version="jev-align.v1",
    )

    with pytest.raises(ValueError, match="unreviewed"):
        workflow.publish(
            (proposal,),
            artifact_id="semantic-reviewed:v1",
            semantic_version="semantic-taxonomy.v1",
            classifier_version="semantic-reviewed.v1",
            diff_report_present=True,
        )
    with pytest.raises(ValueError, match="stale"):
        workflow.review(proposal, SemanticReviewAction.ACCEPT, reviewer="reviewer", current_source_hash="b" * 64)

    accepted = workflow.review(
        proposal,
        SemanticReviewAction.ACCEPT,
        reviewer="reviewer",
        current_source_hash=SOURCE_HASH,
    )
    artifact = workflow.publish(
        (accepted,),
        artifact_id="semantic-reviewed:v1",
        semantic_version="semantic-taxonomy.v1",
        classifier_version="semantic-reviewed.v1",
        diff_report_present=True,
    )
    assert artifact.mappings[0].state is SemanticProposalState.ACCEPTED
    assert artifact.mappings[0].feature.review_status is SemanticReviewStatus.REVIEWED


def test_reviewed_mapping_overrides_rule_output_only_for_matching_source() -> None:
    queue_item = build_review_queue((_candidate(_value()),))[0]
    workflow = SemanticReviewWorkflow()
    proposal = workflow.propose(
        queue_item,
        feature_id=queue_item.values[0].feature_id,
        feature=queue_item.values[0].model_copy(update={"value": Decimal("0.95")}),
        tool_version="jev-align.v1",
    )
    accepted = workflow.review(proposal, SemanticReviewAction.ACCEPT, reviewer="reviewer", current_source_hash=SOURCE_HASH)
    artifact = workflow.publish(
        (accepted,),
        artifact_id="semantic-reviewed:v1",
        semantic_version="semantic-taxonomy.v1",
        classifier_version="semantic-reviewed.v1",
        diff_report_present=True,
    )
    classifier = ReviewedMappingSemanticClassifier(RuleBasedSemanticClassifier(), artifact)
    result = classifier.classify(
        SemanticClassificationInput(
            discipline_id="discipline:aaaaaaaaaaaaaaaa",
            curriculum_item_id="curriculum-item:program:09.03.03-01:discipline:aaaaaaaaaaaaaaaa:1",
            normalized_name="математический анализ",
            source_text="Математический анализ",
            source_hash=SOURCE_HASH,
        )
    )
    assert result.values[0].value == Decimal("0.95")
