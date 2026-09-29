"""Version identifiers for rebuildable derived contracts."""

from __future__ import annotations

from .ids import SemanticVersion

SEMANTIC_TAXONOMY_VERSION: SemanticVersion = "semantic-taxonomy.v1"
SEMANTIC_CLASSIFIER_VERSION: SemanticVersion = "semantic-classifier.v1"
ANALYTICS_PROJECTION_SCHEMA_VERSION: SemanticVersion = "analytics-projection.v1"
METRIC_REGISTRY_VERSION: SemanticVersion = "metric-registry.v1"
DECISION_POLICY_VERSION: SemanticVersion = "decision-policy.v2"
RESPONSE_POLICY_VERSION: SemanticVersion = "response-policy.v1"
ADMISSION_BENEFITS_SCHEMA_VERSION: SemanticVersion = "admission-benefits-schema.v1"
ADMISSION_BENEFITS_PARSER_VERSION: SemanticVersion = "admission-benefits-parser.v1"
ADMISSION_BENEFITS_POLICY_VERSION: SemanticVersion = "admission-benefits-policy.v1"

__all__ = [
    "ADMISSION_BENEFITS_PARSER_VERSION",
    "ADMISSION_BENEFITS_POLICY_VERSION",
    "ADMISSION_BENEFITS_SCHEMA_VERSION",
    "ANALYTICS_PROJECTION_SCHEMA_VERSION",
    "DECISION_POLICY_VERSION",
    "METRIC_REGISTRY_VERSION",
    "RESPONSE_POLICY_VERSION",
    "SEMANTIC_CLASSIFIER_VERSION",
    "SEMANTIC_TAXONOMY_VERSION",
]
