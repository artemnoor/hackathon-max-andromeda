"""Fail-closed production/shadow Jev composition helpers."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from andromeda.infrastructure.config.settings import Settings
from andromeda.modules.conversation.contracts.policy import DecisionPolicyPort
from andromeda.modules.conversation.services.decision_model import (
    RuleBasedDecisionModel,
)
from andromeda.modules.conversation.services.model_decision_policy import (
    ModelBackedDecisionPolicy,
    ShadowDecisionPolicy,
)
from andromeda.modules.conversation.services.rule_decision_policy import (
    RuleBasedDecisionPolicy,
)
from andromeda.modules.entity_resolution.contracts.ports import BoundedCandidateSelector

from .adapter import JevAdapterConfig, JevDecisionModelAdapter
from .admission_resolution import JevAdmissionCandidateSelector
from .calibration import CascadeCalibrationAdapter
from .question_registry import QuestionRegistry
from .typesafe_client import TypeSafeJevTransport

logger = logging.getLogger("andromeda.infrastructure.jev.runtime")


@dataclass(frozen=True, slots=True)
class JevCapabilityReport:
    enabled: bool
    shadow: bool
    provider: str
    model: str
    reason: str
    lock_id: str | None = None


def build_decision_policy(
    settings: Settings,
) -> tuple[DecisionPolicyPort, JevCapabilityReport]:
    deterministic = RuleBasedDecisionPolicy()
    if not settings.jev_enabled and not settings.jev_shadow_enabled:
        return deterministic, _report(settings, reason="disabled_by_config")
    try:
        registry = QuestionRegistry.from_file(_registry_path())
        calibration = None
        lock_id = None
        if settings.jev_enabled:
            if not settings.jev_calibration_enabled:
                raise RuntimeError("calibration_gate_disabled")
            if not settings.jev_calibration_lock_path:
                raise RuntimeError("calibration_lock_missing")
            lock_path = Path(settings.jev_calibration_lock_path)
            calibration = CascadeCalibrationAdapter(
                lock_path=lock_path,
                manifest_path=Path(f"{lock_path}.meta.json"),
                registry=registry,
                model=settings.jev_model,
                production=True,
                min_support=settings.jev_calibration_min_support,
                min_heldout=settings.jev_calibration_min_heldout,
                max_age_seconds=settings.jev_calibration_max_age_seconds,
                required_definition_ids=("next-action.v1",),
            )
            lock_id = calibration.artifact_id
        if settings.jev_api_key is None:
            raise RuntimeError("provider_key_missing")
        transport = TypeSafeJevTransport(
            api_key=settings.jev_api_key,
            endpoint=settings.jev_endpoint,
            model=settings.jev_model,
            registry=registry,
            timeout_seconds=settings.jev_timeout_seconds,
        )
        if not transport.health_check():
            raise RuntimeError("provider_health_failed")
        model = JevDecisionModelAdapter(
            transport,
            RuleBasedDecisionModel(),
            config=JevAdapterConfig(
                timeout_seconds=settings.jev_timeout_seconds,
                max_retries=1,
                provider=settings.jev_runtime_provider,
                model=settings.jev_model,
            ),
            registry=registry,
            calibration=calibration,
        )
        if settings.jev_shadow_enabled:
            policy: DecisionPolicyPort = ShadowDecisionPolicy(model, deterministic)
            report = _report(settings, reason="shadow_enabled", lock_id=lock_id)
        else:
            policy = ModelBackedDecisionPolicy(model, deterministic)
            report = _report(settings, reason="production_enabled", lock_id=lock_id)
        _log_report(report)
        return policy, report
    except Exception as exc:
        report = _report(settings, reason=type(exc).__name__)
        _log_report(report)
        return deterministic, report


def build_admission_candidate_selector(
    settings: Settings,
) -> tuple[BoundedCandidateSelector | None, JevCapabilityReport]:
    """Build the calibrated, opt-in candidate selector; otherwise fail closed."""

    if not settings.jev_admission_resolution_enabled:
        report = JevCapabilityReport(
            enabled=False,
            shadow=False,
            provider=settings.jev_runtime_provider,
            model=settings.jev_model,
            reason="admission_resolution_disabled_by_config",
        )
        return None, report
    try:
        registry = QuestionRegistry.from_file(_admission_registry_path())
        lock_path_value = settings.jev_admission_resolution_lock_path
        if not settings.jev_calibration_enabled or not lock_path_value:
            raise RuntimeError("admission_resolution_calibration_missing")
        lock_path = Path(lock_path_value)
        calibration = CascadeCalibrationAdapter(
            lock_path=lock_path,
            manifest_path=Path(f"{lock_path}.meta.json"),
            registry=registry,
            model=settings.jev_model,
            production=True,
            min_support=settings.jev_calibration_min_support,
            min_heldout=settings.jev_calibration_min_heldout,
            max_age_seconds=settings.jev_calibration_max_age_seconds,
        )
        if settings.jev_api_key is None:
            raise RuntimeError("provider_key_missing")
        transport = TypeSafeJevTransport(
            api_key=settings.jev_api_key,
            endpoint=settings.jev_endpoint,
            model=settings.jev_model,
            registry=registry,
            timeout_seconds=settings.jev_timeout_seconds,
        )
        if not transport.health_check():
            transport.close()
            raise RuntimeError("provider_health_failed")
        model = JevDecisionModelAdapter(
            transport,
            RuleBasedDecisionModel(),
            config=JevAdapterConfig(
                timeout_seconds=settings.jev_timeout_seconds,
                max_retries=1,
                provider=settings.jev_runtime_provider,
                model=settings.jev_model,
            ),
            registry=registry,
            calibration=calibration,
        )
        report = JevCapabilityReport(
            enabled=True,
            shadow=False,
            provider=settings.jev_runtime_provider,
            model=settings.jev_model,
            reason="admission_resolution_production_enabled",
            lock_id=calibration.artifact_id,
        )
        logger.info(
            "jev_admission_resolution_composed enabled=true provider=%s model=%s definition=olympiad-profile-resolution.v1 lock_id=%s",
            report.provider,
            report.model,
            report.lock_id,
        )
        return JevAdmissionCandidateSelector(model), report
    except Exception as exc:
        report = JevCapabilityReport(
            enabled=False,
            shadow=False,
            provider=settings.jev_runtime_provider,
            model=settings.jev_model,
            reason=type(exc).__name__,
        )
        logger.warning(
            "jev_admission_resolution_composed enabled=false provider=%s model=%s reason=%s",
            report.provider,
            report.model,
            report.reason,
        )
        return None, report


def _registry_path() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "config"
        / "jev"
        / "question-definitions.v1.yaml"
    )


def _admission_registry_path() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "config"
        / "jev"
        / "question-definitions.admission.v1.yaml"
    )


def _report(
    settings: Settings, *, reason: str, lock_id: str | None = None
) -> JevCapabilityReport:
    return JevCapabilityReport(
        enabled=settings.jev_enabled and reason == "production_enabled",
        shadow=settings.jev_shadow_enabled and reason == "shadow_enabled",
        provider=settings.jev_runtime_provider,
        model=settings.jev_model,
        reason=reason,
        lock_id=lock_id,
    )


def _log_report(report: JevCapabilityReport) -> None:
    logger.info(
        "jev_capability enabled=%s shadow=%s provider=%s model=%s reason=%s lock_id=%s",
        report.enabled,
        report.shadow,
        report.provider,
        report.model,
        report.reason,
        report.lock_id or "none",
    )


__all__ = [
    "JevCapabilityReport",
    "build_admission_candidate_selector",
    "build_decision_policy",
]
