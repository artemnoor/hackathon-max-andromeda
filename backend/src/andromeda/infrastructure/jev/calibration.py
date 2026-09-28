"""Thin compatibility adapter around the upstream jevcal runtime Cascade."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

from .contracts import JevAnswerEvidence
from .question_registry import QuestionRegistry

logger = logging.getLogger("andromeda.infrastructure.jev.calibration")


class CalibrationArtifactError(ValueError):
    """Raised when a jevcal artifact cannot be trusted by the runtime."""


class CascadeCalibrationAdapter:
    """Delegate trust semantics to the pinned upstream ``jevcal.runtime.Cascade``."""

    def __init__(
        self,
        *,
        lock_path: str | Path,
        manifest_path: str | Path,
        registry: QuestionRegistry,
        model: str,
        production: bool = False,
        min_support: int = 30,
        min_heldout: int = 30,
        max_age_seconds: int | None = None,
        required_definition_ids: tuple[str, ...] | None = None,
    ) -> None:
        self._lock_path = Path(lock_path)
        self._manifest_path = Path(manifest_path)
        self._registry = registry
        self._lock, self._manifest = _load_compatible_artifact(
            self._lock_path,
            self._manifest_path,
            registry,
            model=model,
            production=production,
            min_support=min_support,
            min_heldout=min_heldout,
            max_age_seconds=max_age_seconds,
            required_definition_ids=required_definition_ids,
        )
        try:
            from jevcal.runtime import Cascade  # type: ignore[import-untyped]
        except ImportError as exc:  # pragma: no cover - optional dependency guard
            raise CalibrationArtifactError("jevcal optional dependency is not installed") from exc
        self._cascade_type = Cascade
        logger.info(
            "jevcal_cascade_adapter_loaded artifact_id=%s status=%s model=%s",
            self.artifact_id,
            self._manifest.get("status"),
            model,
        )

    @property
    def artifact_id(self) -> str:
        value = self._manifest.get("artifact_id")
        return value if isinstance(value, str) else "unknown"

    @property
    def manifest(self) -> Mapping[str, object]:
        return self._manifest

    def evaluate(
        self,
        definition_id: str,
        evidence: JevAnswerEvidence,
        *,
        model_version: str | None = None,
    ) -> "GateDecision":
        """Evaluate one provider answer using upstream Cascade semantics."""

        if definition_id not in self._lock["questions"]:
            raise CalibrationArtifactError(f"definition is absent from jevcal lock: {definition_id}")
        if not evidence.probabilities:
            logger.warning(
                "jevcal_cascade_rejected definition_id=%s reason=probabilities_missing",
                definition_id,
            )
            return GateDecision(
                accepted=False,
                answer=evidence.answer_value,
                confidence=None,
                threshold=None,
                source="unresolved",
                reason="probabilities_missing",
                artifact_id=self.artifact_id,
            )
        expected_model_version = self._manifest.get("model_observed")
        if self._manifest.get("source_kind") == "production" and (
            not isinstance(expected_model_version, str)
            or model_version != expected_model_version
        ):
            logger.warning(
                "jevcal_cascade_rejected definition_id=%s reason=model_version_mismatch expected=%s observed=%s",
                definition_id,
                expected_model_version or "missing",
                model_version or "missing",
            )
            return GateDecision(
                accepted=False,
                answer=evidence.answer_value,
                confidence=None,
                threshold=None,
                source="unresolved",
                reason="model_version_mismatch",
                artifact_id=self.artifact_id,
            )

        provider = _SingleAnswerProvider(definition_id, evidence)
        cascade = self._cascade_type(self._lock, provider=provider)
        decision = cascade.decide({}, row={})[definition_id]
        result = GateDecision(
            accepted=decision.source in {"jev", "fallback"},
            answer=decision.answer,
            confidence=decision.confidence,
            threshold=decision.threshold,
            source=decision.source,
            reason="accepted" if decision.source == "jev" else "calibration_rejected",
            artifact_id=self.artifact_id,
        )
        logger.info(
            "jevcal_cascade_evaluated definition_id=%s source=%s accepted=%s artifact_id=%s",
            definition_id,
            result.source,
            result.accepted,
            result.artifact_id,
        )
        return result


class GateDecision:
    """Safe adapter view of an upstream jevcal ``Decision``."""

    __slots__ = ("accepted", "answer", "confidence", "threshold", "source", "reason", "artifact_id")

    def __init__(
        self,
        *,
        accepted: bool,
        answer: object,
        confidence: float | None,
        threshold: float | None,
        source: str,
        reason: str,
        artifact_id: str,
    ) -> None:
        self.accepted = accepted
        self.answer = answer
        self.confidence = confidence
        self.threshold = threshold
        self.source = source
        self.reason = reason
        self.artifact_id = artifact_id


class _SingleAnswerProvider:
    def __init__(self, definition_id: str, evidence: JevAnswerEvidence) -> None:
        self._definition_id = definition_id
        self._evidence = evidence

    def ask(self, state: object, questions: Mapping[str, object], *, row: object | None = None) -> dict[str, object]:
        del state, row
        answers: dict[str, object] = {}
        for question_id, question in questions.items():
            if question_id == self._definition_id:
                answers[question_id] = {
                    "answer": self._evidence.answer_value,
                    "probabilities": self._evidence.probabilities,
                    "confidence": self._evidence.confidence,
                }
                continue
            options = getattr(question, "options", lambda: ["unknown", "resolved"])()
            first = options[0] if options else "unknown"
            second = options[1] if len(options) > 1 else "resolved"
            answers[question_id] = {
                "answer": first,
                "probabilities": {str(first): 0.5, str(second): 0.5},
                "confidence": 0.5,
            }
        return {"answers": answers}


def _load_compatible_artifact(
    lock_path: Path,
    manifest_path: Path,
    registry: QuestionRegistry,
    *,
    model: str,
    production: bool,
    min_support: int,
    min_heldout: int,
    max_age_seconds: int | None,
    required_definition_ids: tuple[str, ...] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationArtifactError("calibration lock/manifest cannot be read") from exc
    if not isinstance(lock, dict) or not isinstance(manifest, dict):
        raise CalibrationArtifactError("calibration lock/manifest must be objects")
    if manifest.get("lock_hash") != _hash_value(lock):
        raise CalibrationArtifactError("calibration lock hash is stale")
    if manifest.get("registry_hash") != registry.content_hash():
        raise CalibrationArtifactError("calibration registry hash is stale")
    if production and manifest.get("status") != "production_ready":
        raise CalibrationArtifactError("calibration artifact is not production-ready")
    if not production and manifest.get("status") not in {"fixture_only", "shadow_only", "production_ready"}:
        raise CalibrationArtifactError("calibration artifact status is invalid")
    if lock.get("model_requested") != model:
        raise CalibrationArtifactError("calibration model does not match configured model")
    versions = manifest.get("definition_versions")
    if not isinstance(versions, dict):
        raise CalibrationArtifactError("calibration definition versions are missing")
    expected_versions = {definition.definition_id: definition.version for definition in registry.all()}
    if versions != expected_versions:
        raise CalibrationArtifactError("calibration definition versions are stale")
    if min_support < 1 or min_heldout < 1:
        raise CalibrationArtifactError("calibration support requirements must be positive")
    raw_lock_questions = lock.get("questions")
    lock_ids = set(raw_lock_questions) if isinstance(raw_lock_questions, dict) else set()
    raw_calibrated_ids = manifest.get("calibrated_definition_ids")
    if raw_calibrated_ids is None:
        calibrated_ids = lock_ids
    elif isinstance(raw_calibrated_ids, (list, tuple, set)):
        calibrated_ids = set(raw_calibrated_ids)
    else:
        raise CalibrationArtifactError("calibration definition scope is missing")
    if not calibrated_ids or calibrated_ids != lock_ids or not calibrated_ids.issubset(expected_versions):
        raise CalibrationArtifactError("calibration definition scope is invalid")
    required_ids = set(required_definition_ids) if required_definition_ids is not None else calibrated_ids
    if not required_ids or not required_ids.issubset(expected_versions):
        raise CalibrationArtifactError("required calibration definition scope is invalid")
    if production:
        if not required_ids.issubset(calibrated_ids):
            raise CalibrationArtifactError("production artifact omits a required definition")
        samples = manifest.get("samples_by_definition")
        if not isinstance(samples, dict):
            raise CalibrationArtifactError("calibration sample counts are missing")
        for definition_id in required_ids:
            value = samples.get(definition_id)
            if not isinstance(value, dict):
                raise CalibrationArtifactError(f"calibration sample counts missing: {definition_id}")
            if int(value.get("total", 0)) < min_support or int(value.get("heldout", 0)) < min_heldout:
                raise CalibrationArtifactError(f"calibration support is insufficient: {definition_id}")
            quality = manifest.get("quality_by_definition")
            result = quality.get(definition_id) if isinstance(quality, dict) else None
            if not isinstance(result, dict) or result.get("status") != "ok" or result.get("threshold") is None:
                raise CalibrationArtifactError(f"calibration quality gate failed: {definition_id}")
        observed_models = lock.get("model_observed")
        if not isinstance(observed_models, list) or len(observed_models) != 1:
            raise CalibrationArtifactError("production artifact must identify one observed model version")
        if manifest.get("model_observed") != observed_models[0]:
            raise CalibrationArtifactError("production observed model version is inconsistent")
    if max_age_seconds is not None and max_age_seconds < 0:
        raise CalibrationArtifactError("calibration max age must not be negative")
    if max_age_seconds is not None:
        created = lock.get("created")
        if not isinstance(created, str):
            raise CalibrationArtifactError("calibration creation timestamp is missing")
        try:
            age = (datetime.now(UTC) - datetime.fromisoformat(created)).total_seconds()
        except ValueError as exc:
            raise CalibrationArtifactError("calibration creation timestamp is invalid") from exc
        if age > max_age_seconds:
            raise CalibrationArtifactError("calibration artifact is stale")
    return lock, manifest


def _hash_value(value: object) -> str:
    canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["CalibrationArtifactError", "CascadeCalibrationAdapter", "GateDecision"]
