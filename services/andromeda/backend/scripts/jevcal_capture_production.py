"""Capture a bounded, synthetic next-action corpus through the official SDK."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import statistics
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from andromeda.infrastructure.config.settings import Settings
from andromeda.infrastructure.jev.contracts import JevRequestEnvelope
from andromeda.infrastructure.jev.question_registry import QuestionRegistry
from andromeda.infrastructure.jev.typesafe_client import TypeSafeJevTransport
from andromeda.modules.conversation.contracts.policy import (
    DecisionAction,
    DecisionModelOperation,
)
from andromeda.modules.conversation.contracts.public import (
    ConversationIntent,
    ConversationSlot,
    NextAction,
    QuerySession,
)
from andromeda.modules.conversation.services.rule_decision_policy import (
    RuleBasedDecisionPolicy,
)
from andromeda.modules.proftest.contracts.public import ProfileScope

logger = logging.getLogger("andromeda.scripts.jevcal_capture_production")
REGISTRY_PATH = ROOT / "config" / "jev" / "question-definitions.v1.yaml"
DEFAULT_CASES_PATH = ROOT / "evals" / "jev" / "corpus" / "production-next-action.v2.jsonl"
DEFAULT_OBSERVATIONS_PATH = (
    ROOT / "evals" / "jev" / "corpus" / "production-next-action-observations.v2.jsonl"
)
DEFAULT_CASE_COUNT = 120
MAX_CASE_COUNT = 120
HOLDOUT = 0.5
SEED = 7


class LiveCaptureError(RuntimeError):
    """Raised when the live evaluation capture is incomplete or unsafe."""


def build_cases(registry: QuestionRegistry, *, count: int = DEFAULT_CASE_COUNT) -> tuple[dict[str, object], ...]:
    """Create deterministic synthetic states labelled by the production fallback policy."""

    if not 1 <= count <= MAX_CASE_COUNT:
        raise ValueError(f"case count must be between 1 and {MAX_CASE_COUNT}")
    definition = registry.for_operation(DecisionModelOperation.CHOOSE_NEXT_ACTION.value)
    action_codes = tuple(action.value for action in DecisionAction)
    metric_sets = (
        ("mathematics_share",),
        ("programming_share",),
        ("ai_ml_share",),
        ("physics_share",),
        ("statistics_share",),
        ("business_share",),
        ("mathematics_share", "programming_share"),
        ("programming_share", "ai_ml_share"),
        ("physics_share", "statistics_share"),
        ("mathematics_share", "business_share"),
    )
    clarification_cases = (
        (NextAction.ASK_FOR_METRIC, ConversationSlot.METRIC),
        (NextAction.ASK_FOR_ENTITY, ConversationSlot.ENTITY),
        (NextAction.ASK_FOR_EXAMS, ConversationSlot.EXAMS),
        (NextAction.ASK_FOR_UNIVERSITY_SCOPE, ConversationSlot.UNIVERSITY_SCOPE),
        (NextAction.CLARIFY, ConversationSlot.ENTITY),
    )
    policy = RuleBasedDecisionPolicy()
    cases: list[dict[str, object]] = []

    def append_case(
        *,
        intent: ConversationIntent,
        next_action: NextAction,
        metrics: tuple[str, ...],
        missing_slots: tuple[ConversationSlot, ...],
    ) -> None:
        index = len(cases) + 1
        case_id = f"next-action-live-v2-{index:03d}"
        session = _query_session(case_id, intent, next_action, metrics, missing_slots)
        expected = policy.decide(session, available_actions=tuple(DecisionAction)).action.value
        payload = {
            "intent": intent.value,
            "metrics": list(metrics),
            "missing_slots": [slot.value for slot in missing_slots],
            "next_action": next_action.value,
            "available_actions": list(action_codes),
        }
        cases.append(
            {
                "case_id": case_id,
                "definition_id": definition.definition_id,
                "definition_version": definition.version,
                "split": "heldout" if _in_holdout(case_id) else "train",
                "input": payload,
                "expected": {"action": expected},
            }
        )

    # Each required clarification branch is represented with varied intent/metric context.
    for branch_index, (next_action, missing_slot) in enumerate(clarification_cases):
        for variant in range(10):
            intent = tuple(ConversationIntent)[(branch_index + variant) % len(ConversationIntent)]
            append_case(
                intent=intent,
                next_action=next_action,
                metrics=metric_sets[(branch_index * 3 + variant) % len(metric_sets)],
                missing_slots=(missing_slot,),
            )

    # The parser's empty/unknown case must remain a clarification, not a guessed query.
    for variant in range(10):
        append_case(
            intent=ConversationIntent.UNKNOWN,
            next_action=NextAction.NONE,
            metrics=(),
            missing_slots=(),
        )

    # Distinguish explicit comparisons from ordinary ready-to-run analytics/admission requests.
    for variant in range(30):
        append_case(
            intent=ConversationIntent.COMPARE_PROGRAMS,
            next_action=NextAction.EXECUTE_QUERY,
            metrics=metric_sets[variant % len(metric_sets)],
            missing_slots=(),
        )
    for variant in range(30):
        intent = (
            ConversationIntent.ANALYTICS_QUERY
            if variant % 2 == 0
            else ConversationIntent.ADMISSION_SEARCH
        )
        append_case(
            intent=intent,
            next_action=NextAction.EXECUTE_QUERY,
            metrics=metric_sets[(variant + 4) % len(metric_sets)] if intent is ConversationIntent.ANALYTICS_QUERY else (),
            missing_slots=(),
        )

    return tuple(cases[:count])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--output-observations", type=Path, default=DEFAULT_OBSERVATIONS_PATH)
    parser.add_argument("--count", type=int, default=DEFAULT_CASE_COUNT)
    parser.add_argument("--max-live-calls", type=int, default=MAX_CASE_COUNT)
    parser.add_argument("--timeout-seconds", type=float, default=20.0)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

    if args.count > args.max_live_calls or args.max_live_calls > MAX_CASE_COUNT:
        raise SystemExit("live call count exceeds the explicit bounded budget")
    if args.timeout_seconds <= 0 or args.timeout_seconds > 30:
        raise SystemExit("timeout must be between 0 and 30 seconds")
    if args.output_cases.exists() or args.output_observations.exists():
        raise SystemExit("refusing to overwrite an existing corpus or observation artifact")

    settings = Settings.from_environment()
    if settings.jev_api_key is None:
        raise SystemExit("JEV_API_KEY or TYPESAFE_API_KEY is required in this process")
    registry = QuestionRegistry.from_file(REGISTRY_PATH)
    definition = registry.for_operation(DecisionModelOperation.CHOOSE_NEXT_ACTION.value)
    cases = build_cases(registry, count=args.count)
    heldout_count = sum(case["split"] == "heldout" for case in cases)
    if heldout_count < 30:
        raise SystemExit(f"synthetic holdout count is insufficient: {heldout_count}")

    try:
        from typesafe_sdk import RetryPolicy, TypeSafeClient, TypeSafeError
    except ImportError as exc:
        raise SystemExit("install the jev evaluation and official SDK extras") from exc

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
    logger.info(
        "jev_live_capture_started definition=%s cases=%d max_model_calls=%d retries=0 endpoint_host=%s model=%s holdout=%d",
        definition.definition_id,
        len(cases),
        args.max_live_calls,
        endpoint_host,
        settings.jev_model,
        heldout_count,
    )

    observations: list[dict[str, object]] = []
    latencies: list[int] = []
    correct_count = 0
    try:
        if not transport.health_check():
            raise LiveCaptureError("provider health check failed")
        for index, case in enumerate(cases, start=1):
            request = _request_for_case(
                case,
                definition=definition,
                timeout_seconds=args.timeout_seconds,
            )
            started = time.monotonic()
            try:
                response = transport.request_envelope(request)
            except TypeSafeError as exc:
                logger.error(
                    "jev_live_capture_request_failed completed=%d planned=%d error=%s",
                    index - 1,
                    len(cases),
                    type(exc).__name__,
                )
                raise LiveCaptureError(
                    f"provider request {index}/{len(cases)} failed: {type(exc).__name__}"
                ) from None
            latency_ms = int((time.monotonic() - started) * 1000)
            if response.failure is not None:
                raise LiveCaptureError(
                    f"provider request {index}/{len(cases)} failed: {response.failure.reason.value}"
                )
            evidence = response.evidence
            if evidence is None or evidence.answer_kind != "ChoiceAnswer":
                raise LiveCaptureError(f"provider request {index}/{len(cases)} returned no choice evidence")
            answer = evidence.answer_value
            expected = case["expected"]
            if not isinstance(answer, str) or not isinstance(expected, dict):
                raise LiveCaptureError(f"provider request {index}/{len(cases)} returned an invalid action")
            probabilities = _validate_probabilities(evidence.probabilities, tuple(DecisionAction))
            gold = expected.get("action")
            if not isinstance(gold, str):
                raise LiveCaptureError(f"case {case['case_id']} has no typed gold action")
            correct = answer == gold
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
                    "prediction": answer,
                    "correct": correct,
                    "confidence": evidence.confidence,
                    "probabilities": probabilities,
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
                    "jev_live_capture_progress completed=%d planned=%d accuracy=%.3f latency_ms_p50=%d",
                    index,
                    len(cases),
                    correct_count / index,
                    int(statistics.median(latencies)),
                )
    finally:
        transport.close()

    observed_models = {str(row["model_observed"]) for row in observations}
    observed_providers = {str(row["provider"]) for row in observations}
    if len(observed_models) != 1 or "unknown" in observed_models:
        raise LiveCaptureError("live responses do not have one stable, identifiable model version")
    if len(observed_providers) != 1:
        raise LiveCaptureError("live responses came from multiple providers")

    args.output_cases.parent.mkdir(parents=True, exist_ok=True)
    args.output_observations.parent.mkdir(parents=True, exist_ok=True)
    _write_jsonl(args.output_cases, cases)
    _write_jsonl(args.output_observations, observations)
    report = {
        "status": "captured_live_observations",
        "provider": next(iter(observed_providers)),
        "endpoint_host": endpoint_host,
        "model_requested": settings.jev_model,
        "model_observed": next(iter(observed_models)),
        "definition_id": definition.definition_id,
        "model_calls": len(observations),
        "retry_limit": 0,
        "accuracy_against_deterministic_policy": correct_count / len(observations),
        "correct": correct_count,
        "heldout": heldout_count,
        "latency_ms_p50": int(statistics.median(latencies)),
        "latency_ms_p95": _percentile(latencies, 0.95),
        "prediction_counts": dict(Counter(str(row["prediction"]) for row in observations)),
        "cases_path": str(args.output_cases),
        "observations_path": str(args.output_observations),
        "dataset_hash": _canonical_hash(cases),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def _request_for_case(
    case: dict[str, object], *, definition: Any, timeout_seconds: float
) -> JevRequestEnvelope:
    payload = case.get("input")
    if not isinstance(payload, dict):
        raise LiveCaptureError("case input must be a mapping")
    return JevRequestEnvelope(
        definition_id=definition.definition_id,
        definition_version=definition.version,
        definition_kind=definition.kind,
        operation=DecisionModelOperation.CHOOSE_NEXT_ACTION,
        redacted_payload=payload,
        correlation_id=f"calibration-{case['case_id']}",
        timeout_seconds=timeout_seconds,
        timeout_class=definition.timeout_class,
        pii_policy=definition.pii_policy,
        output_schema=definition.output_schema,
    )


def _query_session(
    case_id: str,
    intent: ConversationIntent,
    next_action: NextAction,
    metrics: tuple[str, ...],
    missing_slots: tuple[ConversationSlot, ...],
) -> QuerySession:
    now = datetime(2026, 9, 23, tzinfo=UTC)
    digest = hashlib.sha256(case_id.encode("utf-8")).hexdigest()
    return QuerySession(
        session_id=f"query-session:{digest[:32]}",
        owner_scope=ProfileScope(session_key_hash=digest),
        intent=intent,
        metrics=metrics,
        missing_slots=missing_slots,
        next_action=next_action,
        revision=1,
        created_at=now,
        updated_at=now,
        expires_at=now + timedelta(days=1),
    )


def _validate_probabilities(
    probabilities: dict[str, float], actions: tuple[DecisionAction, ...]
) -> dict[str, float]:
    expected_labels = {action.value for action in actions}
    if set(probabilities) != expected_labels:
        raise LiveCaptureError("provider probability labels do not match the registered action set")
    if any(not math.isfinite(value) or not 0 <= value <= 1 for value in probabilities.values()):
        raise LiveCaptureError("provider returned an invalid probability value")
    if not math.isclose(sum(probabilities.values()), 1.0, abs_tol=0.02):
        raise LiveCaptureError("provider probability vector does not sum to one")
    return {key: probabilities[key] for key in sorted(probabilities)}


def _in_holdout(case_id: str) -> bool:
    try:
        from jevcal.metrics import in_holdout  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - guarded in main
        raise RuntimeError("upstream jevcal is required") from exc
    return bool(in_holdout(case_id, HOLDOUT, SEED))


def _write_jsonl(path: Path, rows: tuple[dict[str, object], ...] | list[dict[str, object]]) -> None:
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _canonical_hash(value: object) -> str:
    serialized = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _percentile(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


if __name__ == "__main__":
    raise SystemExit(main())
