"""Strict, provider-neutral boundary for an optional external decision model."""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import uuid4

from andromeda.modules.analytics.contracts.results import AnalyticsResult
from andromeda.modules.analytics.domain.metric_registry import MetricRegistry
from andromeda.modules.conversation.contracts.decision_definitions import (
    DecisionDefinitionKind,
    DecisionOutputSchema,
    DecisionPiiPolicy,
    DecisionTimeoutClass,
    QuestionRegistryPort,
)
from andromeda.modules.conversation.contracts.policy import (
    CandidateResolutionDecision,
    CandidateResolutionOption,
    ConfidenceBucket,
    DataCapabilities,
    DecisionAction,
    DecisionModelOperation,
    DecisionModelPort,
    DecisionModelSource,
    IntentDecision,
    MetricDecision,
    NextActionDecision,
    PresentationDecision,
    SemanticFeatureDecision,
)
from andromeda.modules.conversation.contracts.public import (
    ConversationIntent,
    NextAction,
    QuerySession,
)
from andromeda.modules.presentation.contracts.policy import (
    PresentationCapabilities,
    ResponseRequest,
)

from .calibration import CascadeCalibrationAdapter
from .contracts import (
    JevFailure,
    JevFailureReason,
    JevRequestEnvelope,
    JevResponseEnvelope,
    JevUsage,
    ModelIdentity,
)

logger = logging.getLogger("andromeda.infrastructure.jev.adapter")
_ALLOWED_TEMPLATES = {
    "analytics-summary",
    "metric-comparison",
    "metric-cards",
    "analytics-report",
    "analytics-explorer",
}


class JevTransport(Protocol):
    """Legacy provider-neutral transport retained for existing adapters."""

    def request(
        self, operation: str, payload: Mapping[str, object], *, timeout_seconds: float
    ) -> object: ...


class JevEnvelopeTransport(Protocol):
    """Typed transport used by new production/provider adapters."""

    def request_envelope(self, request: JevRequestEnvelope) -> object: ...


@dataclass(frozen=True, slots=True)
class JevAdapterConfig:
    timeout_seconds: float = 2.0
    enrichment_timeout_seconds: float = 10.0
    evaluation_timeout_seconds: float = 30.0
    max_retries: int = 1
    max_failures: int = 3
    circuit_open_seconds: float = 30.0
    max_output_bytes: int = 32_000
    provider: str = "jev"
    model: str = "decision-model"
    model_version: str = "unknown"


@dataclass(frozen=True, slots=True)
class _DefinitionMetadata:
    definition_id: str
    version: str
    kind: DecisionDefinitionKind
    timeout_class: DecisionTimeoutClass
    pii_policy: DecisionPiiPolicy
    output_schema: DecisionOutputSchema


class _JevBoundaryError(Exception):
    def __init__(self, reason: JevFailureReason, detail_code: str) -> None:
        super().__init__(detail_code)
        self.reason = reason
        self.detail_code = detail_code


_EMPTY_OUTPUT_SCHEMA = DecisionOutputSchema()
_LEGACY_DEFINITIONS: dict[DecisionModelOperation, _DefinitionMetadata] = {
    DecisionModelOperation.RESOLVE_INTENT: _DefinitionMetadata(
        "intent.v1",
        "intent-definition.v1",
        DecisionDefinitionKind.INTENT,
        DecisionTimeoutClass.INTERACTIVE,
        DecisionPiiPolicy.SANITIZED,
        _EMPTY_OUTPUT_SCHEMA,
    ),
    DecisionModelOperation.RESOLVE_METRIC: _DefinitionMetadata(
        "metric.v1",
        "metric-definition.v1",
        DecisionDefinitionKind.METRIC,
        DecisionTimeoutClass.INTERACTIVE,
        DecisionPiiPolicy.SANITIZED,
        _EMPTY_OUTPUT_SCHEMA,
    ),
    DecisionModelOperation.CHOOSE_NEXT_ACTION: _DefinitionMetadata(
        "next-action.v1",
        "next-action-definition.v2",
        DecisionDefinitionKind.NEXT_ACTION,
        DecisionTimeoutClass.INTERACTIVE,
        DecisionPiiPolicy.SANITIZED,
        _EMPTY_OUTPUT_SCHEMA,
    ),
    DecisionModelOperation.CHOOSE_PRESENTATION: _DefinitionMetadata(
        "presentation.v1",
        "presentation-definition.v1",
        DecisionDefinitionKind.PRESENTATION,
        DecisionTimeoutClass.INTERACTIVE,
        DecisionPiiPolicy.SANITIZED,
        _EMPTY_OUTPUT_SCHEMA,
    ),
    DecisionModelOperation.CLASSIFY_SEMANTIC_FEATURES: _DefinitionMetadata(
        "semantic-feature.v1",
        "semantic-feature-definition.v1",
        DecisionDefinitionKind.SEMANTIC_FEATURE,
        DecisionTimeoutClass.ENRICHMENT,
        DecisionPiiPolicy.SANITIZED,
        _EMPTY_OUTPUT_SCHEMA,
    ),
    DecisionModelOperation.RESOLVE_OLYMPIAD_PROFILE: _DefinitionMetadata(
        "olympiad-profile-resolution.v1",
        "olympiad-profile-resolution-definition.v1",
        DecisionDefinitionKind.ENTITY_RESOLUTION,
        DecisionTimeoutClass.INTERACTIVE,
        DecisionPiiPolicy.SANITIZED,
        _EMPTY_OUTPUT_SCHEMA,
    ),
}


class JevDecisionModelAdapter(DecisionModelPort):
    """Validate every external answer and fall back to deterministic behavior."""

    def __init__(
        self,
        transport: JevTransport | JevEnvelopeTransport,
        fallback: DecisionModelPort,
        *,
        config: JevAdapterConfig | None = None,
        registry: QuestionRegistryPort | None = None,
        calibration: CascadeCalibrationAdapter | None = None,
    ) -> None:
        self._transport = transport
        self._fallback = fallback
        self._config = config or JevAdapterConfig()
        if (
            self._config.timeout_seconds <= 0
            or self._config.enrichment_timeout_seconds <= 0
            or self._config.evaluation_timeout_seconds <= 0
            or self._config.max_retries < 0
            or self._config.max_retries > 3
            or self._config.max_failures < 1
            or self._config.max_output_bytes < 1
        ):
            raise ValueError("invalid Jev adapter bounds")
        self._failures = 0
        self._circuit_open_until = 0.0
        self._metric_registry = MetricRegistry()
        self._registry = registry
        self._calibration = calibration

    def resolve_intent(self, text: str) -> IntentDecision:
        if len(text) > 2000:
            return self._fallback_intent(text, "input_too_large")
        response = self._call(DecisionModelOperation.RESOLVE_INTENT, {"text": text})
        failure_reason = self._response_failure_reason(response)
        if failure_reason is not None:
            return self._fallback_intent(text, failure_reason)
        try:
            value = IntentDecision.model_validate(response.payload, strict=False)
            return value.model_copy(
                update={
                    "operation": DecisionModelOperation.RESOLVE_INTENT,
                    "source": DecisionModelSource.JEV,
                    "model_version": response.identity.model_version,
                }
            )
        except (TypeError, ValueError):
            return self._fallback_intent(text, "invalid_provider_output")

    def resolve_metric(
        self, text: str, *, candidates: tuple[str, ...] = ()
    ) -> MetricDecision:
        if len(text) > 2000:
            return self._fallback_metric(text, candidates, "input_too_large")
        response = self._call(
            DecisionModelOperation.RESOLVE_METRIC,
            {"text": text, "candidates": candidates[:8]},
        )
        failure_reason = self._response_failure_reason(response)
        if failure_reason is not None:
            return self._fallback_metric(text, candidates, failure_reason)
        try:
            value = MetricDecision.model_validate(response.payload, strict=False)
            if (
                value.metric_code is not None
                and candidates
                and value.metric_code not in candidates
            ):
                raise ValueError("provider returned a metric outside the candidate set")
            if value.metric_code is not None:
                self._metric_registry.get(value.metric_code)
            return value.model_copy(
                update={
                    "operation": DecisionModelOperation.RESOLVE_METRIC,
                    "source": DecisionModelSource.JEV,
                    "model_version": response.identity.model_version,
                }
            )
        except (TypeError, ValueError):
            return self._fallback_metric(text, candidates, "invalid_provider_output")

    def choose_next_action(
        self,
        session: QuerySession,
        *,
        available_actions: tuple[DecisionAction, ...] = tuple(DecisionAction),
        capabilities: DataCapabilities | None = None,
        last_result: AnalyticsResult | None = None,
    ) -> NextActionDecision:
        payload = {
            "intent": session.intent.value,
            "metrics": session.metrics,
            "missing_slots": tuple(slot.value for slot in session.missing_slots),
            "next_action": session.next_action.value,
            "available_actions": tuple(action.value for action in available_actions),
        }
        response = self._call(DecisionModelOperation.CHOOSE_NEXT_ACTION, payload)
        failure_reason = self._response_failure_reason(response)
        if failure_reason is not None:
            return self._fallback_next_action(
                session, available_actions, capabilities, last_result, failure_reason
            )
        try:
            value = NextActionDecision.model_validate(response.payload, strict=False)
            if value.decision.action not in available_actions:
                raise ValueError("provider returned a forbidden action")
            deterministic = self._fallback.choose_next_action(
                session,
                available_actions=available_actions,
                capabilities=capabilities,
                last_result=last_result,
            )
            if not _action_is_applicable(
                value.decision.action,
                session,
                last_result=last_result,
                deterministic_action=deterministic.decision.action,
            ):
                return self._fallback_next_action(
                    session,
                    available_actions,
                    capabilities,
                    last_result,
                    "action_not_applicable",
                )
            if value.decision.action is DecisionAction.ASK_CLARIFICATION:
                # The model selects whether to ask; exact wording/options remain deterministic.
                value = value.model_copy(
                    update={
                        "decision": deterministic.decision.model_copy(
                            update={
                                "reason": "TypeSafe selected clarification; prompt supplied by deterministic policy"
                            }
                        )
                    }
                )
            return value.model_copy(
                update={
                    "operation": DecisionModelOperation.CHOOSE_NEXT_ACTION,
                    "source": DecisionModelSource.JEV,
                    "model_version": response.identity.model_version,
                }
            )
        except (TypeError, ValueError):
            return self._fallback_next_action(
                session,
                available_actions,
                capabilities,
                last_result,
                "invalid_provider_output",
            )

    def choose_presentation(
        self,
        request: ResponseRequest,
        *,
        capabilities: PresentationCapabilities | None = None,
    ) -> PresentationDecision:
        response = self._call(
            DecisionModelOperation.CHOOSE_PRESENTATION,
            {
                "comparison_requested": request.comparison_requested,
                "report_requested": request.report_requested,
                "interactive_requested": request.interactive_requested,
                "capabilities": (capabilities or PresentationCapabilities()).model_dump(
                    mode="json"
                ),
            },
        )
        failure_reason = self._response_failure_reason(response)
        if failure_reason is not None:
            return self._fallback_presentation(request, capabilities, failure_reason)
        try:
            value = PresentationDecision.model_validate(response.payload, strict=False)
            if value.template not in _ALLOWED_TEMPLATES:
                raise ValueError("provider returned a forbidden presentation template")
            return value.model_copy(
                update={
                    "operation": DecisionModelOperation.CHOOSE_PRESENTATION,
                    "source": DecisionModelSource.JEV,
                    "model_version": response.identity.model_version,
                }
            )
        except (TypeError, ValueError):
            return self._fallback_presentation(
                request, capabilities, "invalid_provider_output"
            )

    def classify_semantic_features(
        self,
        input_text: str,
        *,
        feature_codes: tuple[str, ...] = (),
    ) -> SemanticFeatureDecision:
        if len(input_text) > 2000:
            return self._fallback_semantic(input_text, feature_codes, "input_too_large")
        response = self._call(
            DecisionModelOperation.CLASSIFY_SEMANTIC_FEATURES,
            {"text": input_text, "feature_codes": feature_codes[:64]},
        )
        failure_reason = self._response_failure_reason(response)
        if failure_reason is not None:
            return self._fallback_semantic(input_text, feature_codes, failure_reason)
        try:
            value = SemanticFeatureDecision.model_validate(
                response.payload, strict=False
            )
            allowed = set(feature_codes)
            if (
                any(
                    item.feature_id.removeprefix("semantic-feature:") not in allowed
                    for item in value.values
                )
                and allowed
            ):
                raise ValueError("provider returned an unknown semantic feature")
            return value.model_copy(
                update={
                    "operation": DecisionModelOperation.CLASSIFY_SEMANTIC_FEATURES,
                    "source": DecisionModelSource.JEV,
                    "model_version": response.identity.model_version,
                }
            )
        except (TypeError, ValueError):
            return self._fallback_semantic(
                input_text, feature_codes, "invalid_provider_output"
            )

    def resolve_olympiad_profile(
        self,
        text: str,
        *,
        candidates: tuple[CandidateResolutionOption, ...],
    ) -> CandidateResolutionDecision:
        # Candidate selection is a production control decision, not a UI hint.
        # Unlike shadowable operations, it must never trust an uncalibrated
        # provider response.
        if self._calibration is None:
            return self._fallback_candidate(text, candidates, "calibration_unavailable")
        candidate_ids = tuple(item.candidate_id for item in candidates)
        if len(text) > 1200 or not candidates or len(candidates) > 8:
            return self._fallback_candidate(
                text, candidates, "input_or_candidate_budget"
            )
        if len(candidate_ids) != len(set(candidate_ids)):
            return self._fallback_candidate(text, candidates, "duplicate_candidate_id")
        sanitized_text = _sanitize_candidate_query(text, candidates)
        if not sanitized_text:
            return self._fallback_candidate(text, candidates, "no_candidate_terms")
        response = self._call(
            DecisionModelOperation.RESOLVE_OLYMPIAD_PROFILE,
            {
                "text": sanitized_text,
                "candidates": tuple(
                    {"candidate_id": item.candidate_id, "label": item.label}
                    for item in candidates
                ),
            },
        )
        failure_reason = self._response_failure_reason(response)
        if failure_reason is not None:
            return self._fallback_candidate(text, candidates, failure_reason)
        try:
            value = CandidateResolutionDecision.model_validate(
                response.payload, strict=False
            )
            if (
                value.candidate_id is not None
                and value.candidate_id not in candidate_ids
            ):
                raise ValueError(
                    "provider returned a candidate outside the supplied set"
                )
            return value.model_copy(
                update={
                    "operation": DecisionModelOperation.RESOLVE_OLYMPIAD_PROFILE,
                    "source": DecisionModelSource.JEV,
                    "model_version": response.identity.model_version,
                }
            )
        except (TypeError, ValueError):
            return self._fallback_candidate(text, candidates, "invalid_provider_output")

    def _call(
        self, operation: DecisionModelOperation, payload: Mapping[str, object]
    ) -> JevResponseEnvelope:
        definition = self._definition_for(operation)
        if definition is None:
            logger.error(
                "jev_request_fallback operation=%s fallback_reason=artifact_missing",
                operation.value,
            )
            return self._failure_response(
                operation,
                JevFailureReason.ARTIFACT_MISSING,
                detail_code="question_definition_missing",
            )

        timeout_seconds = self._timeout_for(definition.timeout_class)
        request = JevRequestEnvelope(
            definition_id=definition.definition_id,
            definition_version=definition.version,
            definition_kind=definition.kind,
            operation=operation,
            redacted_payload=self._redact_payload(payload),
            correlation_id=f"jev:{uuid4().hex}",
            timeout_seconds=timeout_seconds,
            timeout_class=definition.timeout_class,
            pii_policy=definition.pii_policy,
            output_schema=definition.output_schema,
        )

        now = time.monotonic()
        if now < self._circuit_open_until:
            return self._failure_response(
                operation,
                JevFailureReason.PROVIDER_UNAVAILABLE,
                detail_code="circuit_open",
            )

        attempts = self._config.max_retries + 1
        for attempt in range(attempts):
            started = time.monotonic()
            logger.info(
                "jev_request_started operation=%s definition_version=%s source=jev attempt=%s",
                request.operation.value,
                request.definition_version,
                attempt + 1,
            )
            try:
                raw_response = self._request_transport(request)
                if (
                    len(repr(raw_response).encode("utf-8"))
                    > self._config.max_output_bytes
                ):
                    raise _JevBoundaryError(JevFailureReason.BUDGET, "output_too_large")
                response = self._normalize_response(raw_response, request, started)
                if response.failure is not None:
                    self._failures += 1
                    logger.warning(
                        "jev_request_fallback operation=%s definition_version=%s fallback_reason=%s retry_count=%s",
                        request.operation.value,
                        request.definition_version,
                        response.failure.reason.value,
                        attempt,
                    )
                    if attempt + 1 < attempts and response.failure.retryable:
                        continue
                    return response

                if self._calibration is not None:
                    if response.evidence is None:
                        logger.warning(
                            "jev_request_fallback operation=%s definition_id=%s fallback_reason=calibration_evidence_missing",
                            request.operation.value,
                            request.definition_id,
                        )
                        return self._failure_response(
                            operation,
                            JevFailureReason.CALIBRATION_REJECTED,
                            detail_code="calibration_evidence_missing",
                        )
                    gate = self._calibration.evaluate(
                        request.definition_id,
                        response.evidence,
                        model_version=response.identity.model_version,
                    )
                    if not gate.accepted:
                        logger.warning(
                            "jev_request_fallback operation=%s definition_id=%s fallback_reason=calibration_rejected artifact_id=%s",
                            request.operation.value,
                            request.definition_id,
                            gate.artifact_id,
                        )
                        return self._failure_response(
                            operation,
                            JevFailureReason.CALIBRATION_REJECTED,
                            detail_code=gate.reason,
                        )

                self._failures = 0
                logger.info(
                    "[FIX:jev-model-identity] jev_request_completed operation=%s definition_version=%s source=%s provider=%s model=%s model_version=%s latency_ms=%s retry_count=%s confidence_bucket=%s input_tokens=%s output_tokens=%s",
                    request.operation.value,
                    request.definition_version,
                    response.identity.source.value,
                    response.identity.provider,
                    response.identity.model,
                    response.identity.model_version,
                    int((time.monotonic() - started) * 1000),
                    attempt,
                    "unknown",
                    response.usage.input_tokens,
                    response.usage.output_tokens,
                )
                return response
            except _JevBoundaryError as exc:
                failure = self._failure_response(
                    operation,
                    exc.reason,
                    detail_code=exc.detail_code,
                )
            except TimeoutError:
                failure = self._failure_response(
                    operation, JevFailureReason.TIMEOUT, detail_code="transport_timeout"
                )
            except PermissionError:
                failure = self._failure_response(
                    operation, JevFailureReason.AUTH, detail_code="transport_auth"
                )
            except Exception as exc:  # provider boundary: fallback must be total
                failure = self._failure_response(
                    operation,
                    JevFailureReason.TRANSPORT,
                    detail_code=type(exc).__name__,
                )

            self._failures += 1
            logger.warning(
                "jev_request_fallback operation=%s definition_version=%s fallback_reason=%s retry_count=%s",
                request.operation.value,
                request.definition_version,
                failure.failure.reason.value
                if failure.failure is not None
                else "unknown",
                attempt,
            )
            if (
                attempt + 1 < attempts
                and failure.failure is not None
                and failure.failure.retryable
            ):
                continue
            if self._failures >= self._config.max_failures:
                self._circuit_open_until = (
                    time.monotonic() + self._config.circuit_open_seconds
                )
            return failure
        return self._failure_response(
            operation,
            JevFailureReason.PROVIDER_UNAVAILABLE,
            detail_code="retry_budget_exhausted",
        )

    def _definition_for(
        self, operation: DecisionModelOperation
    ) -> _DefinitionMetadata | None:
        if self._registry is None:
            return _LEGACY_DEFINITIONS[operation]
        try:
            definition = self._registry.for_operation(operation.value)
        except (KeyError, ValueError):
            return None
        return _DefinitionMetadata(
            definition_id=definition.definition_id,
            version=definition.version,
            kind=definition.kind,
            timeout_class=definition.timeout_class,
            pii_policy=definition.pii_policy,
            output_schema=definition.output_schema,
        )

    def _timeout_for(self, timeout_class: DecisionTimeoutClass) -> float:
        if timeout_class is DecisionTimeoutClass.ENRICHMENT:
            return self._config.enrichment_timeout_seconds
        if timeout_class is DecisionTimeoutClass.EVALUATION:
            return self._config.evaluation_timeout_seconds
        return self._config.timeout_seconds

    def _request_transport(self, request: JevRequestEnvelope) -> object:
        request_envelope = getattr(self._transport, "request_envelope", None)
        if callable(request_envelope):
            return request_envelope(request)
        request_legacy = getattr(self._transport, "request", None)
        if not callable(request_legacy):
            raise TypeError(
                "Jev transport does not implement a supported request method"
            )
        return request_legacy(
            request.operation.value,
            request.redacted_payload,
            timeout_seconds=request.timeout_seconds,
        )

    def _normalize_response(
        self,
        raw_response: object,
        request: JevRequestEnvelope,
        started: float,
    ) -> JevResponseEnvelope:
        if isinstance(raw_response, JevResponseEnvelope):
            return raw_response
        if isinstance(raw_response, Mapping) and {"payload", "failure"}.intersection(
            raw_response
        ):
            try:
                return JevResponseEnvelope.model_validate(raw_response, strict=False)
            except (TypeError, ValueError):
                logger.warning(
                    "jev_schema_rejected operation=%s definition_version=%s reason=response_envelope",
                    request.operation.value,
                    request.definition_version,
                )
                return self._failure_response(
                    operation=request.operation,
                    reason=JevFailureReason.SCHEMA,
                    detail_code="response_envelope",
                )

        return JevResponseEnvelope(
            payload=raw_response,
            identity=ModelIdentity(
                provider=self._config.provider,
                model=self._config.model,
                model_version=self._config.model_version,
                source=DecisionModelSource.JEV,
                artifact_id=f"{request.definition_id}@{request.definition_version}",
            ),
            usage=JevUsage(latency_ms=int((time.monotonic() - started) * 1000)),
        )

    def _failure_response(
        self,
        operation: DecisionModelOperation,
        reason: JevFailureReason,
        *,
        detail_code: str,
    ) -> JevResponseEnvelope:
        definition = _LEGACY_DEFINITIONS.get(operation)
        artifact_id = (
            f"{definition.definition_id}@{definition.version}"
            if definition is not None
            else f"operation:{operation.value}"
        )
        retryable = reason in {
            JevFailureReason.TIMEOUT,
            JevFailureReason.TRANSPORT,
            JevFailureReason.RATE_LIMIT,
            JevFailureReason.PROVIDER_UNAVAILABLE,
        }
        return JevResponseEnvelope(
            identity=ModelIdentity(
                provider=self._config.provider,
                model=self._config.model,
                model_version=self._config.model_version,
                source=DecisionModelSource.FALLBACK,
                artifact_id=artifact_id,
            ),
            failure=JevFailure(
                reason=reason, retryable=retryable, detail_code=detail_code
            ),
        )

    @staticmethod
    def _response_failure_reason(response: JevResponseEnvelope | None) -> str | None:
        if response is None or response.failure is None:
            return None
        if response.failure.reason in {
            JevFailureReason.TIMEOUT,
            JevFailureReason.TRANSPORT,
            JevFailureReason.AUTH,
            JevFailureReason.RATE_LIMIT,
            JevFailureReason.PROVIDER_UNAVAILABLE,
        }:
            return "provider_unavailable"
        return response.failure.reason.value

    @staticmethod
    def _redact_payload(payload: Mapping[str, object]) -> dict[str, object]:
        sensitive_keys = {
            "api_key",
            "authorization",
            "cookie",
            "password",
            "secret",
            "token",
        }
        redacted: dict[str, object] = {}
        for key, value in payload.items():
            if key.lower() in sensitive_keys:
                redacted[key] = "[REDACTED]"
            elif isinstance(value, str):
                redacted[key] = value[:8_000]
            elif isinstance(value, (tuple, list)):
                redacted[key] = tuple(
                    item[:128] if isinstance(item, str) else item for item in value[:64]
                )
            else:
                redacted[key] = value
        return redacted

    def _fallback_intent(self, text: str, reason: str) -> IntentDecision:
        try:
            value = self._fallback.resolve_intent(text)
        except Exception:
            from andromeda.modules.conversation.contracts.public import (
                ConversationIntent,
            )

            return IntentDecision(
                intent=ConversationIntent.UNKNOWN,
                source=DecisionModelSource.FALLBACK,
                confidence=ConfidenceBucket.UNAVAILABLE,
                fallback_reason=reason,
            )
        return value.model_copy(
            update={"source": DecisionModelSource.FALLBACK, "fallback_reason": reason}
        )

    def _fallback_metric(
        self, text: str, candidates: tuple[str, ...], reason: str
    ) -> MetricDecision:
        try:
            value = self._fallback.resolve_metric(text, candidates=candidates)
        except Exception:
            value = MetricDecision(
                metric_code=None,
                source=DecisionModelSource.FALLBACK,
                confidence=ConfidenceBucket.UNAVAILABLE,
            )
        return value.model_copy(
            update={"source": DecisionModelSource.FALLBACK, "fallback_reason": reason}
        )

    def _fallback_next_action(
        self,
        session: QuerySession,
        available_actions: tuple[DecisionAction, ...],
        capabilities: DataCapabilities | None,
        last_result: AnalyticsResult | None,
        reason: str,
    ) -> NextActionDecision:
        value = self._fallback.choose_next_action(
            session,
            available_actions=available_actions,
            capabilities=capabilities,
            last_result=last_result,
        )
        return value.model_copy(
            update={"source": DecisionModelSource.FALLBACK, "fallback_reason": reason}
        )

    def _fallback_presentation(
        self,
        request: ResponseRequest,
        capabilities: PresentationCapabilities | None,
        reason: str,
    ) -> PresentationDecision:
        value = self._fallback.choose_presentation(request, capabilities=capabilities)
        return value.model_copy(
            update={"source": DecisionModelSource.FALLBACK, "fallback_reason": reason}
        )

    def _fallback_semantic(
        self,
        input_text: str,
        feature_codes: tuple[str, ...],
        reason: str,
    ) -> SemanticFeatureDecision:
        value = self._fallback.classify_semantic_features(
            input_text, feature_codes=feature_codes
        )
        return value.model_copy(
            update={"source": DecisionModelSource.FALLBACK, "fallback_reason": reason}
        )

    def _fallback_candidate(
        self,
        text: str,
        candidates: tuple[CandidateResolutionOption, ...],
        reason: str,
    ) -> CandidateResolutionDecision:
        del text, candidates
        return CandidateResolutionDecision(
            source=DecisionModelSource.FALLBACK,
            confidence=ConfidenceBucket.UNAVAILABLE,
            model_version=self._config.model_version,
            fallback_reason=reason,
        )


def _sanitize_candidate_query(
    text: str,
    candidates: tuple[CandidateResolutionOption, ...],
) -> str:
    """Send only words that overlap source-backed names, never profile context."""

    query_terms = re.findall(r"[^\W\d_]+", text.casefold(), flags=re.UNICODE)
    candidate_terms = tuple(
        re.findall(r"[^\W\d_]+", item.label.casefold(), flags=re.UNICODE)
        for item in candidates
    )
    selected = tuple(
        term
        for term in query_terms
        if len(term) >= 4
        and any(
            term == candidate_term
            or (
                min(len(term), len(candidate_term)) >= 4
                and (term.startswith(candidate_term) or candidate_term.startswith(term))
            )
            for label_terms in candidate_terms
            for candidate_term in label_terms
        )
    )
    return " ".join(selected)[:1200]


def _action_is_applicable(
    action: DecisionAction,
    session: QuerySession,
    *,
    last_result: AnalyticsResult | None,
    deterministic_action: DecisionAction,
) -> bool:
    """Reject unsafe/impossible actions before they reach application orchestration."""

    if action is DecisionAction.ASK_CLARIFICATION:
        return deterministic_action is DecisionAction.ASK_CLARIFICATION
    if action is DecisionAction.EXECUTE_QUERY:
        return deterministic_action is not DecisionAction.ASK_CLARIFICATION
    if action is DecisionAction.COMPARE:
        return (
            session.intent is ConversationIntent.COMPARE_PROGRAMS
            and session.next_action is NextAction.EXECUTE_QUERY
        )
    if action is DecisionAction.SHOW_RESULT:
        return last_result is not None
    # These actions are declared for future clients but are not executable by
    # the current AssistantService transport path, so fail closed for now.
    return False


__all__ = [
    "JevAdapterConfig",
    "JevDecisionModelAdapter",
    "JevEnvelopeTransport",
    "JevTransport",
]
