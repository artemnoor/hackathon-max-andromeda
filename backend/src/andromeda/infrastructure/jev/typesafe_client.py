"""Production transport for the official TypeSafe Python SDK.

The SDK is imported lazily so the core application remains installable without
the optional provider extra.  This adapter only translates registered,
allow-listed decision definitions into System One primitives; it never accepts
arbitrary prompts, SQL, or provider endpoints from a request.
"""

from __future__ import annotations

import importlib
import logging
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from andromeda.modules.conversation.contracts.decision_definitions import (
    DecisionDefinition,
    QuestionRegistryPort,
)

from .contracts import (
    JevAnswerEvidence,
    JevRequestEnvelope,
    JevResponseEnvelope,
    JevUsage,
    ModelIdentity,
)

_ALLOWED_ENDPOINTS = frozenset(("https://api.typesafe.ai", "https://polza.ai/api"))
_POLZA_ENDPOINT = "https://polza.ai/api"
_INTENT_LABEL_TO_DOMAIN = {
    "catalog_search": "analytics_query",
    "comparison": "compare_programs",
    "admission_search": "admission_search",
    "recommendation": "unknown",
    "unknown": "unknown",
}
logger = logging.getLogger("andromeda.infrastructure.jev.typesafe_client")


class TypeSafeJevTransport:
    """Typed adapter around ``typesafe_sdk.TypeSafeClient.system_one``."""

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        model: str,
        registry: QuestionRegistryPort,
        timeout_seconds: float = 2.0,
        client_factory: Callable[..., Any] | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("TypeSafe API key must not be empty")
        if endpoint not in _ALLOWED_ENDPOINTS:
            raise ValueError("TypeSafe endpoint is not an approved HTTPS endpoint")
        if not model.strip():
            raise ValueError("TypeSafe model must not be empty")
        self._api_key = api_key
        self._endpoint = endpoint
        self._model = model
        self._registry = registry
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory
        self._client: Any | None = None

    def request_envelope(self, request: JevRequestEnvelope) -> JevResponseEnvelope:
        definition = self._registry.get(request.definition_id)
        started = time.monotonic()
        response = self._client_or_create().system_one(
            state=_bounded_state(request.redacted_payload),
            questions=_questions_for(definition, request.redacted_payload),
            model=self._model,
            timeout=request.timeout_seconds,
        )
        payload = _payload_for(definition, response)
        evidence = _evidence_for(response)
        usage = getattr(response, "usage", None)
        return JevResponseEnvelope(
            payload=payload,
            identity=ModelIdentity(
                provider="polza" if self._endpoint == _POLZA_ENDPOINT else "typesafe",
                model=self._model,
                model_version=getattr(response, "model", self._model),
                artifact_id=f"{definition.definition_id}@{definition.version}",
            ),
            usage=JevUsage(
                input_tokens=getattr(usage, "input_tokens", None),
                output_tokens=getattr(usage, "output_tokens", None),
                retry_count=getattr(usage, "n_retries", None),
                malformed_retry_count=getattr(
                    usage, "n_retries_malformed_structure", None
                ),
                latency_ms=int((time.monotonic() - started) * 1000),
            ),
            evidence=evidence,
        )

    def health_check(self) -> bool:
        started = time.monotonic()
        try:
            if self._endpoint == _POLZA_ENDPOINT:
                response = httpx.get(
                    f"{self._endpoint}/v1/models",
                    headers={"Authorization": f"Bearer {self._api_key}"},
                    timeout=self._timeout_seconds,
                )
                response.raise_for_status()
                payload = response.json()
                records = payload.get("data", payload.get("models", ()))
                available = isinstance(records, list) and any(
                    isinstance(item, Mapping)
                    and (item.get("id") or item.get("name")) == self._model
                    for item in records
                )
                logger.info(
                    "typesafe_health_check provider=polza outcome=%s model=%s latency_ms=%s",
                    "available" if available else "model_missing",
                    self._model,
                    int((time.monotonic() - started) * 1000),
                )
                return available
            response = self._client_or_create().models.list(
                timeout=self._timeout_seconds
            )
            models = getattr(response, "models", ())
            available = any(
                getattr(item, "name", None) == self._model
                or getattr(item, "id", None) == self._model
                for item in models
            )
            logger.info(
                "typesafe_health_check provider=typesafe outcome=%s model=%s latency_ms=%s",
                "available" if available else "model_missing",
                self._model,
                int((time.monotonic() - started) * 1000),
            )
            return available
        except Exception as exc:  # noqa: BLE001 - a health probe must degrade closed for SDK/provider failures
            logger.warning(
                "typesafe_health_check outcome=unavailable provider=%s error=%s latency_ms=%s",
                "polza" if self._endpoint == _POLZA_ENDPOINT else "typesafe",
                type(exc).__name__,
                int((time.monotonic() - started) * 1000),
            )
            return False

    def close(self) -> None:
        if self._client is not None:
            close = getattr(self._client, "close", None)
            if callable(close):
                close()
            self._client = None

    def _client_or_create(self) -> Any:
        if self._client is not None:
            return self._client
        factory = self._client_factory or _official_client_factory
        self._client = factory(
            api_key=self._api_key,
            model=self._model,
            base_url=self._endpoint,
            timeout=self._timeout_seconds,
        )
        return self._client


def _official_client_factory(**kwargs: Any) -> Any:
    try:
        module = importlib.import_module("typesafe_sdk")
        client_type = module.TypeSafeClient
    except ImportError as exc:
        raise RuntimeError("typesafe-sdk optional dependency is not installed") from exc
    return client_type(**kwargs)


def _bounded_state(payload: Mapping[str, object]) -> dict[str, object]:
    state: dict[str, object] = {}
    for key, value in payload.items():
        if len(state) >= 32:
            break
        if isinstance(value, str):
            state[key] = value[:8_000]
        elif isinstance(value, (bool, int, float)):
            state[key] = value
        elif isinstance(value, (tuple, list)):
            state[key] = tuple(
                item[:256] if isinstance(item, str) else item for item in value[:64]
            )
        elif isinstance(value, Mapping):
            state[key] = {
                str(inner_key): inner_value
                for inner_key, inner_value in list(value.items())[:32]
            }
    return state


def _questions_for(
    definition: DecisionDefinition, payload: Mapping[str, object]
) -> dict[str, object]:
    try:
        from typesafe_sdk import Choice, Noul
    except ImportError as exc:  # pragma: no cover - optional dependency guard
        raise RuntimeError("typesafe-sdk optional dependency is not installed") from exc
    options = _dynamic_options(definition, payload)
    if definition.operation == "classify_semantic_features":
        feature_codes = _string_tuple(payload.get("feature_codes"))
        return {
            code: Noul(
                instructions=f"{definition.instructions} Evaluate feature code {code}; return true only when supported by the supplied discipline text."
            )
            for code in feature_codes[:64]
        }
    if definition.operation == "resolve_olympiad_profile":
        options = _candidate_options(payload.get("candidates"))
        options["unresolved"] = "The phrase does not identify one supplied candidate."
        return {
            "answer": Choice(
                instructions=definition.instructions,
                criteria=options,
            )
        }
    if not options:
        raise ValueError(
            f"registered decision has no bounded options: {definition.definition_id}"
        )
    return {"answer": Choice(instructions=definition.instructions, criteria=options)}


def _dynamic_options(
    definition: DecisionDefinition, payload: Mapping[str, object]
) -> dict[str, str]:
    if definition.operation == "resolve_metric":
        candidates = _string_tuple(payload.get("candidates"))
        options = {
            candidate: candidate
            for candidate in candidates[:8]
            if candidate != "unresolved"
        }
        options["unresolved"] = "The phrase does not identify one supplied metric."
        return options
    if definition.operation == "choose_next_action":
        candidates = _string_tuple(payload.get("available_actions"))
        return {candidate: candidate for candidate in candidates[:16]}
    if definition.operation == "choose_presentation":
        return {value: value for value in definition.output_schema.allowed_values}
    if definition.operation == "resolve_olympiad_profile":
        return _candidate_options(payload.get("candidates"))
    return {option.code: option.description for option in definition.options}


def _candidate_options(value: object) -> dict[str, str]:
    if not isinstance(value, (tuple, list)):
        return {}
    options: dict[str, str] = {}
    for item in value[:8]:
        if not isinstance(item, Mapping):
            continue
        candidate_id = item.get("candidate_id")
        label = item.get("label")
        if isinstance(candidate_id, str) and isinstance(label, str):
            options[candidate_id[:256]] = label[:512]
    return options


def _payload_for(definition: DecisionDefinition, response: Any) -> dict[str, object]:
    choices = getattr(response, "choices", {})
    answer = choices.get("answer")
    raw_choice = getattr(answer, "choice", None)
    choice = raw_choice if isinstance(raw_choice, str) else ""
    confidence = _confidence_bucket(getattr(answer, "confidence", None))
    if definition.operation == "resolve_intent":
        # The registry vocabulary is intentionally stable for calibration, while
        # the application contract uses product-domain names. Keep provider
        # probabilities untouched in JevAnswerEvidence; translate only the
        # validated payload that enters the domain adapter.
        return {
            "intent": _INTENT_LABEL_TO_DOMAIN.get(choice, choice),
            "confidence": confidence,
        }
    if definition.operation == "resolve_metric":
        metric_code = choice if choice and choice != "unresolved" else None
        return {
            "metric_code": metric_code,
            "candidates": (metric_code,) if metric_code else (),
            "confidence": confidence,
        }
    if definition.operation == "choose_next_action":
        return {
            "decision": {
                "action": choice,
                "question": None,
                "options": (),
                "reason": "TypeSafe registered choice",
            },
            "confidence": confidence,
        }
    if definition.operation == "choose_presentation":
        template = {
            "text": "analytics-summary",
            "image": "metric-comparison",
            "image_collection": "metric-cards",
            "pdf": "analytics-report",
            "mini_app": "analytics-explorer",
        }.get(choice, "analytics-summary")
        return {
            "response_format": choice,
            "template": template,
            "confidence": confidence,
        }
    if definition.operation == "resolve_olympiad_profile":
        return {
            "candidate_id": choice if choice and choice != "unresolved" else None,
            "confidence": confidence,
        }
    # Noul answers are probabilities, but converting them into source-like
    # semantic values would be unsafe without a feature intensity calibration.
    # Preserve the registered call and let the semantic fallback/review path
    # handle the result until that calibration exists.
    return {"values": (), "confidence": confidence}


def _evidence_for(response: Any) -> JevAnswerEvidence | None:
    choices = getattr(response, "choices", {})
    if not isinstance(choices, Mapping):
        choices = {}
    answer = choices.get("answer")
    if answer is None and choices:
        answer = next(iter(choices.values()))
    if answer is None:
        # The official SDK exposes SystemOneResponse.choices as only the
        # ChoiceAnswer subset. Noul answers are keyed by question in
        # SystemOneResponse.answers / .nouls and carry their positive-class
        # probability in ``noul``. Preserve those raw probabilities for
        # evaluation without translating them into semantic feature values.
        answers = getattr(response, "answers", {})
        if not isinstance(answers, Mapping):
            return None
        noul_probabilities = {
            name: float(probability)
            for name, item in answers.items()
            if isinstance(name, str)
            and isinstance(probability := getattr(item, "noul", None), (int, float))
            and 0 <= probability <= 1
        }
        if not noul_probabilities:
            return None
        return JevAnswerEvidence(
            answer_kind="noul_batch",
            answer_value=noul_probabilities,
            probabilities=noul_probabilities,
            has_probability_evidence=True,
        )
    raw_probabilities = getattr(answer, "probabilities", None)
    probabilities: dict[str, float] = {}
    if isinstance(raw_probabilities, Mapping):
        for key, value in raw_probabilities.items():
            if (
                isinstance(key, str)
                and isinstance(value, (int, float))
                and 0 <= value <= 1
            ):
                probabilities[key] = float(value)
    raw_value = getattr(answer, "choice", None)
    if raw_value is None:
        raw_value = getattr(answer, "noul", None)
    confidence = getattr(answer, "confidence", None)
    if not isinstance(confidence, (int, float)):
        confidence = None
    return JevAnswerEvidence(
        answer_kind=type(answer).__name__,
        answer_value=raw_value,
        confidence=confidence,
        probabilities=probabilities,
        has_probability_evidence=bool(probabilities),
    )


def _string_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, (tuple, list)):
        return ()
    return tuple(item for item in value if isinstance(item, str) and item)


def _confidence_bucket(value: object) -> str:
    if not isinstance(value, (int, float)):
        return "unavailable"
    if value >= 0.8:
        return "high"
    if value >= 0.5:
        return "medium"
    return "low"


__all__ = ["TypeSafeJevTransport"]
