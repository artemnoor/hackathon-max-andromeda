"""Orchestrate upstream jevcal calibration without reimplementing its logic."""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from andromeda.infrastructure.jev.question_registry import QuestionRegistry
from evals.jev.exporters import build_jevcal_bundle

logger = logging.getLogger("andromeda.scripts.jevcal_calibrate")
LOCK_PATH = ROOT / "config" / "jev" / "locks" / "decisions.v1.lock.json"
MANIFEST_PATH = LOCK_PATH.with_suffix(LOCK_PATH.suffix + ".meta.json")
OBSERVATIONS_PATH = (
    ROOT / "evals" / "jev" / "corpus" / "calibration-observations.v1.jsonl"
)
CORPUS_PATH = ROOT / "evals" / "jev" / "corpus" / "decision-cases.v1.jsonl"
PRODUCTION_LOCK_PATH = (
    ROOT / "config" / "jev" / "locks" / "next-action.typesafe-jev.v2.lock.json"
)
PRODUCTION_MANIFEST_PATH = PRODUCTION_LOCK_PATH.with_suffix(
    PRODUCTION_LOCK_PATH.suffix + ".meta.json"
)
PRODUCTION_OBSERVATIONS_PATH = (
    ROOT / "evals" / "jev" / "corpus" / "production-next-action-observations.v2.jsonl"
)
PRODUCTION_CORPUS_PATH = (
    ROOT / "evals" / "jev" / "corpus" / "production-next-action.v2.jsonl"
)
REGISTRY_PATH = ROOT / "config" / "jev" / "question-definitions.v1.yaml"
TARGET_ACCURACY = 0.8
HOLDOUT = 0.5
SEED = 7
MIN_SUPPORT = 30
MIN_PRODUCTION_TOTAL = 100
MIN_PRODUCTION_HELDOUT = 30
MIN_PRODUCTION_LABEL_TOTAL = 5
MIN_PRODUCTION_LABEL_HELDOUT = 2
PRODUCTION_DEFINITION_IDS = ("next-action.v1",)


class CalibrationArtifactError(ValueError):
    """Raised when an upstream artifact or its Andromeda metadata is invalid."""


@dataclass(frozen=True, slots=True)
class CalibrationInputs:
    lock: dict[str, object]
    manifest: dict[str, object]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="validate an existing upstream lock"
    )
    parser.add_argument(
        "--source", choices=("fixture", "production"), default="fixture"
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--definition-id", action="append", dest="definition_ids")
    parser.add_argument("--model")
    parser.add_argument("--min-support", type=int, default=MIN_SUPPORT)
    parser.add_argument("--min-total", type=int, default=MIN_PRODUCTION_TOTAL)
    parser.add_argument("--min-heldout", type=int, default=MIN_PRODUCTION_HELDOUT)
    parser.add_argument(
        "--min-label-total", type=int, default=MIN_PRODUCTION_LABEL_TOTAL
    )
    parser.add_argument(
        "--min-label-heldout", type=int, default=MIN_PRODUCTION_LABEL_HELDOUT
    )
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    if (
        min(
            args.min_support,
            args.min_total,
            args.min_heldout,
            args.min_label_total,
            args.min_label_heldout,
        )
        < 1
    ):
        raise SystemExit("support requirements must be positive")
    default_output = LOCK_PATH if args.source == "fixture" else PRODUCTION_LOCK_PATH
    output = args.output or default_output
    manifest_output = args.manifest_output or output.with_suffix(
        output.suffix + ".meta.json"
    )
    registry_path = args.registry or REGISTRY_PATH
    definition_ids = tuple(args.definition_ids) if args.definition_ids else None
    production_definition_ids = definition_ids or PRODUCTION_DEFINITION_IDS
    corpus_path = args.corpus or (
        CORPUS_PATH if args.source == "fixture" else PRODUCTION_CORPUS_PATH
    )
    observations_path = args.observations or (
        OBSERVATIONS_PATH if args.source == "fixture" else PRODUCTION_OBSERVATIONS_PATH
    )
    if args.check:
        _validate_lock(
            output,
            manifest_output,
            observations_path=observations_path,
            registry_path=registry_path,
            required_definition_ids=production_definition_ids
            if args.source == "production"
            else None,
        )
        print(json.dumps({"valid": True, "lock": str(output)}, indent=2))
        return 0
    if args.source == "production" and not args.model:
        raise SystemExit("--model is required for production calibration")

    lock, results = _build_lock(
        min_support=args.min_support,
        source_kind=args.source,
        corpus_path=corpus_path,
        observations_path=observations_path,
        model=args.model or "jev-latest",
        registry_path=registry_path,
        definition_ids=definition_ids,
    )
    manifest = _build_manifest(
        lock,
        results,
        source_kind=args.source,
        min_support=args.min_support,
        min_total=args.min_total,
        min_heldout=args.min_heldout,
        min_label_total=args.min_label_total,
        min_label_heldout=args.min_label_heldout,
        observations_path=observations_path,
        corpus_path=corpus_path,
        registry_path=registry_path,
        production_definition_ids=production_definition_ids,
    )
    report = {"manifest": manifest, "calibration": results}
    if args.source == "production" and manifest.get("status") != "production_ready":
        reasons = manifest.get("production_gate_reasons")
        reason_text = (
            ",".join(str(reason) for reason in reasons)
            if isinstance(reasons, list)
            else "unknown"
        )
        logger.warning(
            "jevcal_production_gate_rejected reasons=%s",
            reason_text,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    manifest_output.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _validate_lock(
        output,
        manifest_output,
        observations_path=observations_path,
        registry_path=registry_path,
        required_definition_ids=production_definition_ids
        if args.source == "production"
        else None,
    )
    questions = lock.get("questions")
    question_count = len(questions) if isinstance(questions, dict) else 0
    logger.info(
        "jevcal_upstream_artifact_written lock=%s manifest=%s definitions=%s source_kind=%s",
        output,
        manifest_output,
        question_count,
        args.source,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if manifest.get("status") in {"fixture_only", "production_ready"} else 2


def _build_lock(
    *,
    min_support: int = MIN_SUPPORT,
    source_kind: str = "fixture",
    corpus_path: Path = CORPUS_PATH,
    observations_path: Path = OBSERVATIONS_PATH,
    model: str = "jev-latest",
    registry_path: Path = REGISTRY_PATH,
    definition_ids: tuple[str, ...] | None = None,
) -> tuple[dict[str, object], dict[str, dict[str, object]]]:
    """Build an upstream jevcal lock from complete observed choice distributions."""

    try:
        from jevcal.compile import (  # type: ignore[import-untyped]
            build_lock,
            compile_question,
        )
        from jevcal.metrics import (  # type: ignore[import-untyped]
            Record,
            confidence_measures,
            in_holdout,
        )
        from jevcal.spec import (  # type: ignore[import-untyped]
            load_questions,
            load_rows,
        )
    except ImportError as exc:  # pragma: no cover - optional extra guard
        raise CalibrationArtifactError(
            "install the evaluation extra for upstream jevcal"
        ) from exc

    registry = QuestionRegistry.from_file(registry_path)
    source_rows = _read_jsonl(observations_path)
    all_cases = _read_jsonl(corpus_path)
    selected_definition_ids: tuple[str, ...]
    if source_kind == "production":
        selected_definition_ids = definition_ids or PRODUCTION_DEFINITION_IDS
    else:
        if definition_ids is None:
            observed_ids = tuple(
                dict.fromkeys(
                    _required_string(row, "definition_id") for row in source_rows
                )
            )
            # Noul evidence is not exposed as a calibrated Choice by the current runtime adapter.
            selected_definition_ids = tuple(
                item for item in observed_ids if item != "semantic-feature.v1"
            )
        else:
            selected_definition_ids = definition_ids
    if any(
        registry.get(item).kind.value == "semantic_feature"
        for item in selected_definition_ids
    ):
        raise CalibrationArtifactError(
            "Noul semantic features are not Choice-calibrated by this pipeline"
        )
    decision_rows = [
        row for row in all_cases if row.get("definition_id") in selected_definition_ids
    ]
    if not decision_rows or not source_rows:
        raise CalibrationArtifactError(
            "calibration corpus and observations must not be empty"
        )
    bundle = build_jevcal_bundle(
        registry, tuple(decision_rows), definition_ids=selected_definition_ids
    )
    case_by_id = {str(row["id"]): row for row in bundle.rows}
    selected_observations = [
        row
        for row in source_rows
        if row.get("definition_id") in selected_definition_ids
    ]
    observation_ids = [
        _required_string(row, "case_id") for row in selected_observations
    ]
    if len(observation_ids) != len(set(observation_ids)):
        raise CalibrationArtifactError(
            "calibration observation case IDs must be unique"
        )
    if set(observation_ids) != set(case_by_id):
        raise CalibrationArtifactError("corpus and observation case IDs do not match")

    with tempfile.TemporaryDirectory(prefix="andromeda-jevcal-") as directory:
        directory_path = Path(directory)
        questions_path = directory_path / "questions.yaml"
        data_path = directory_path / "data.jsonl"
        questions_path.write_text(
            _questions_yaml(bundle.questions, model=model), encoding="utf-8"
        )
        data_path.write_text(
            # Jevcal reads these temporary files with the platform default
            # encoding. ASCII escapes preserve Unicode values after JSON parse
            # while making the upstream reader deterministic on Windows locales.
            "".join(json.dumps(row, ensure_ascii=True) + "\n" for row in bundle.rows),
            encoding="utf-8",
        )
        questions = load_questions(questions_path)
        rows = load_rows(data_path)
        observations_by_question: dict[str, list[dict[str, object]]] = {}
        for observation in selected_observations:
            question_id = _required_string(observation, "definition_id")
            observations_by_question.setdefault(question_id, []).append(observation)

        results: dict[str, dict[str, object]] = {}
        model_versions: set[str] = set()
        providers: set[str] = set()
        input_tokens = 0
        output_tokens = 0
        for question_id, question in questions.questions.items():
            labels = tuple(question.options())
            records = []
            question_observations = observations_by_question.get(question_id, [])
            if not any(row.get("split") == "heldout" for row in question_observations):
                raise CalibrationArtifactError(
                    f"heldout observations are required: {question_id}"
                )
            for observation in question_observations:
                case_id = _required_string(observation, "case_id")
                native_labels = case_by_id[case_id].get("labels")
                if not isinstance(native_labels, dict):
                    raise CalibrationArtifactError(f"gold label is missing: {case_id}")
                gold = native_labels.get(question_id)
                if not isinstance(gold, str) or gold not in labels:
                    raise CalibrationArtifactError(f"invalid gold label: {case_id}")

                if source_kind == "production":
                    if observation.get("model_requested") != model:
                        raise CalibrationArtifactError(
                            f"requested model mismatch: {case_id}"
                        )
                    if (
                        observation.get("definition_version")
                        != registry.get(question_id).version
                    ):
                        raise CalibrationArtifactError(
                            f"question version mismatch: {case_id}"
                        )
                    expected_split = (
                        "heldout" if in_holdout(case_id, HOLDOUT, SEED) else "train"
                    )
                    if observation.get("split") != expected_split:
                        raise CalibrationArtifactError(
                            f"upstream holdout assignment mismatch: {case_id}"
                        )
                    if (
                        observation.get("capture_method")
                        != "official-typesafe-sdk-system-one"
                    ):
                        raise CalibrationArtifactError(
                            f"observation is not from the official SDK: {case_id}"
                        )
                    if observation.get("gold") != gold:
                        raise CalibrationArtifactError(
                            f"observation gold differs from corpus: {case_id}"
                        )
                    prediction = _required_string(observation, "prediction")
                    probabilities = _probability_distribution(observation, labels)
                    correct = prediction == gold
                    if observation.get("correct") is not correct:
                        raise CalibrationArtifactError(
                            f"observation correctness is inconsistent: {case_id}"
                        )
                    observed_version = _required_string(observation, "model_observed")
                    provider = _required_string(observation, "provider")
                    if observed_version == "unknown":
                        raise CalibrationArtifactError(
                            f"model version is not identifiable: {case_id}"
                        )
                    model_versions.add(observed_version)
                    providers.add(provider)
                    usage = observation.get("usage")
                    if isinstance(usage, dict):
                        input_tokens += _optional_nonnegative_int(
                            usage.get("input_tokens")
                        )
                        output_tokens += _optional_nonnegative_int(
                            usage.get("output_tokens")
                        )
                    provided_confidence = observation.get("confidence")
                    if not isinstance(provided_confidence, (int, float)):
                        raise CalibrationArtifactError(
                            f"model confidence is missing: {case_id}"
                        )
                else:
                    # Fixture-only synthesis keeps this wiring artifact explicitly non-production.
                    fixture_confidence = _probability(observation)
                    prediction = (
                        gold
                        if bool(observation.get("correct"))
                        else next(label for label in labels if label != gold)
                    )
                    probabilities = _fixture_distribution(
                        labels, prediction, fixture_confidence
                    )
                    correct = prediction == gold
                    provided_confidence = fixture_confidence

                records.append(
                    Record(
                        row_id=case_id,
                        qid=question_id,
                        gold=gold,
                        pred=prediction,
                        correct=correct,
                        probabilities=probabilities,
                        gold_key=gold,
                        measures=confidence_measures(
                            probabilities, float(provided_confidence)
                        ),
                    )
                )
            if not records:
                raise CalibrationArtifactError(f"no observations for {question_id}")
            results[question_id] = compile_question(
                records,
                target=TARGET_ACCURACY,
                measure="top_prob",
                holdout=HOLDOUT,
                seed=SEED,
                min_support=min_support,
            )

        if source_kind == "production" and (
            len(model_versions) != 1 or len(providers) != 1
        ):
            raise CalibrationArtifactError(
                "production observations must use one stable model and provider"
            )
        lock = build_lock(
            questions,
            rows,
            results,
            {"models": sorted(model_versions) if model_versions else ["fixture-only"]},
            {
                "captured_model_calls": len(selected_observations),
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }
            if source_kind == "production"
            else None,
            holdout=HOLDOUT,
            seed=SEED,
            provider=next(iter(providers)) if providers else "deterministic-fixture",
        )
    if not isinstance(lock, dict) or "questions" not in lock:
        raise CalibrationArtifactError("upstream jevcal returned an invalid lock")
    return lock, results


def _build_manifest(
    lock: dict[str, object],
    results: dict[str, dict[str, object]],
    *,
    source_kind: str,
    min_support: int,
    min_total: int,
    min_heldout: int,
    min_label_total: int = MIN_PRODUCTION_LABEL_TOTAL,
    min_label_heldout: int = MIN_PRODUCTION_LABEL_HELDOUT,
    observations_path: Path,
    corpus_path: Path,
    registry_path: Path = REGISTRY_PATH,
    production_definition_ids: tuple[str, ...] = PRODUCTION_DEFINITION_IDS,
) -> dict[str, object]:
    registry = QuestionRegistry.from_file(registry_path)
    tool = json.loads(
        (ROOT / "evals" / "jev" / "TOOLS.lock").read_text(encoding="utf-8")
    )["tools"]["jevcal"]
    raw_questions = lock.get("questions")
    definition_ids = (
        sorted(str(key) for key in raw_questions)
        if isinstance(raw_questions, dict)
        else []
    )
    samples = _sample_counts(observations_path, definition_ids)
    source_cases = _read_jsonl(corpus_path)
    bundle = build_jevcal_bundle(
        registry,
        tuple(
            case for case in source_cases if case.get("definition_id") in definition_ids
        ),
        definition_ids=tuple(definition_ids),
    )
    labels_by_definition = {
        definition_id: _criterion_labels(bundle, definition_id)
        for definition_id in definition_ids
    }
    label_support = _label_support(bundle.rows, labels_by_definition)
    quality: dict[str, dict[str, object]] = {}
    gate_reasons: list[str] = []
    for definition_id in definition_ids:
        result = results[definition_id]
        fit_value = result.get("fit")
        fit: dict[str, object] = fit_value if isinstance(fit_value, dict) else {}
        heldout_value = result.get("holdout")
        heldout: dict[str, object] = (
            heldout_value if isinstance(heldout_value, dict) else {}
        )
        calibration_value = result.get("calibration")
        calibration: dict[str, object] = (
            calibration_value if isinstance(calibration_value, dict) else {}
        )
        sample = samples.get(definition_id, {})
        quality[definition_id] = {
            "status": result.get("status"),
            "threshold": result.get("threshold"),
            "fit_samples": result.get("n_fit"),
            "fit_accepted": fit.get("n_accepted"),
            "fit_accepted_accuracy": fit.get("accepted_accuracy"),
            "heldout_samples": result.get("n_holdout"),
            "heldout_accepted": heldout.get("n_accepted"),
            "heldout_accepted_accuracy": heldout.get("accepted_accuracy"),
            "ece": calibration.get("ece"),
            "label_support": label_support.get(definition_id, {}),
        }
        if source_kind == "production":
            if int(sample.get("total", 0)) < min_total:
                gate_reasons.append(f"{definition_id}:total_below_minimum")
            if int(sample.get("heldout", 0)) < min_heldout:
                gate_reasons.append(f"{definition_id}:heldout_below_minimum")
            if result.get("status") != "ok" or not isinstance(
                result.get("threshold"), (int, float)
            ):
                gate_reasons.append(f"{definition_id}:upstream_quality_gate_failed")
            fit_accepted = fit.get("n_accepted", 0)
            if not isinstance(fit_accepted, int) or fit_accepted < min_support:
                gate_reasons.append(
                    f"{definition_id}:accepted_fit_support_below_minimum"
                )
            heldout_accepted = heldout.get("n_accepted", 0)
            if not isinstance(heldout_accepted, int) or heldout_accepted < min_support:
                gate_reasons.append(
                    f"{definition_id}:accepted_heldout_support_below_minimum"
                )
            heldout_accuracy = heldout.get("accepted_accuracy")
            if (
                not isinstance(heldout_accuracy, (int, float))
                or heldout_accuracy < TARGET_ACCURACY
            ):
                gate_reasons.append(f"{definition_id}:heldout_accuracy_below_target")
            for label, support in label_support.get(definition_id, {}).items():
                if support["total"] < min_label_total:
                    gate_reasons.append(
                        f"{definition_id}:label_total_below_minimum:{label}"
                    )
                if support["heldout"] < min_label_heldout:
                    gate_reasons.append(
                        f"{definition_id}:label_heldout_below_minimum:{label}"
                    )

    observed_models = lock.get("model_observed")
    model_observed = (
        observed_models[0]
        if isinstance(observed_models, list) and len(observed_models) == 1
        else None
    )
    observations = _read_jsonl(observations_path)
    providers = (
        {str(row.get("provider")) for row in observations}
        if source_kind == "production"
        else set()
    )
    capture_methods = (
        {str(row.get("capture_method")) for row in observations}
        if source_kind == "production"
        else set()
    )
    endpoint_hosts = (
        {
            str(row.get("endpoint_host"))
            for row in observations
            if row.get("endpoint_host")
        }
        if source_kind == "production"
        else set()
    )
    if source_kind == "production":
        if definition_ids != sorted(production_definition_ids):
            gate_reasons.append("calibration_definition_scope_mismatch")
        if (
            not isinstance(model_observed, str)
            or not model_observed
            or model_observed == "unknown"
        ):
            gate_reasons.append("model_version_missing")
        if len(providers) != 1 or not providers.issubset({"polza", "typesafe"}):
            gate_reasons.append("provider_identity_mismatch")
        if len(endpoint_hosts) != 1 or not endpoint_hosts.issubset(
            {"polza.ai", "api.typesafe.ai"}
        ):
            gate_reasons.append("endpoint_identity_mismatch")
        if capture_methods != {"official-typesafe-sdk-system-one"}:
            gate_reasons.append("capture_method_mismatch")

    lock_hash = _hash_value(lock)
    return {
        "schema_version": "andromeda-jevcal-manifest.v2",
        "artifact_id": "jevcal-lock-" + lock_hash.split(":", 1)[1][:12],
        "source_kind": source_kind,
        "status": "fixture_only"
        if source_kind == "fixture"
        else ("production_ready" if not gate_reasons else "not_production_ready"),
        "production_gate_reasons": gate_reasons,
        "registry_hash": registry.content_hash(),
        "dataset_hash": str(lock.get("dataset_sha", "")),
        "corpus_hash": _hash_file(corpus_path),
        "observations_hash": _hash_file(observations_path),
        "lock_hash": lock_hash,
        "upstream": {
            "name": "jevcal",
            "commit": tool["commit"],
            "version": lock.get("jevcal_version"),
        },
        "provider": next(iter(providers))
        if len(providers) == 1
        else lock.get("provider"),
        "endpoint_host": next(iter(endpoint_hosts))
        if len(endpoint_hosts) == 1
        else None,
        "model_requested": lock.get("model_requested"),
        "model_observed": model_observed,
        "min_support": min_support,
        "min_total": min_total if source_kind == "production" else None,
        "min_heldout": min_heldout if source_kind == "production" else None,
        "min_label_total": min_label_total if source_kind == "production" else None,
        "min_label_heldout": min_label_heldout if source_kind == "production" else None,
        "target_accuracy": TARGET_ACCURACY,
        "samples_by_definition": samples,
        "quality_by_definition": quality,
        "calibrated_definition_ids": definition_ids,
        "definition_versions": {
            definition.definition_id: definition.version
            for definition in registry.all()
        },
    }


def _validate_lock(
    lock_path: Path,
    manifest_path: Path = MANIFEST_PATH,
    *,
    observations_path: Path | None = None,
    registry_path: Path = REGISTRY_PATH,
    required_definition_ids: tuple[str, ...] | None = PRODUCTION_DEFINITION_IDS,
) -> CalibrationInputs:
    try:
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CalibrationArtifactError(
            "calibration artifact or manifest is invalid"
        ) from exc
    if not isinstance(lock, dict) or not isinstance(manifest, dict):
        raise CalibrationArtifactError(
            "calibration artifact and manifest must be objects"
        )
    required_lock = {
        "jevcal_version",
        "questions",
        "questions_sha",
        "dataset_sha",
        "model_requested",
    }
    if not required_lock.issubset(lock):
        raise CalibrationArtifactError("upstream lock is missing required fields")
    if manifest.get("lock_hash") != _hash_value(lock):
        raise CalibrationArtifactError("calibration manifest lock hash is stale")
    if manifest.get("dataset_hash") != lock.get("dataset_sha"):
        raise CalibrationArtifactError("calibration manifest dataset hash is stale")
    source_kind = manifest.get("source_kind")
    selected_observations = observations_path or (
        PRODUCTION_OBSERVATIONS_PATH
        if source_kind == "production"
        else OBSERVATIONS_PATH
    )
    if manifest.get("observations_hash") != _hash_file(selected_observations):
        raise CalibrationArtifactError("calibration observations hash is stale")
    registry = QuestionRegistry.from_file(registry_path)
    question_ids = (
        set(lock["questions"]) if isinstance(lock["questions"], dict) else set()
    )
    expected_ids = {definition.definition_id for definition in registry.all()}
    manifest_ids = manifest.get("calibrated_definition_ids", sorted(question_ids))
    if not isinstance(manifest_ids, list) or set(manifest_ids) != question_ids:
        raise CalibrationArtifactError(
            "manifest calibration scope does not match upstream lock"
        )
    if not question_ids or not question_ids.issubset(expected_ids):
        raise CalibrationArtifactError(
            "upstream lock contains unknown or no registry definitions"
        )
    if manifest.get("registry_hash") != registry.content_hash():
        raise CalibrationArtifactError("calibration manifest registry hash is stale")
    if source_kind == "production":
        if manifest.get("status") != "production_ready":
            raise CalibrationArtifactError(
                "production calibration gates are not satisfied"
            )
        observed = lock.get("model_observed")
        if (
            not isinstance(observed, list)
            or len(observed) != 1
            or manifest.get("model_observed") != observed[0]
        ):
            raise CalibrationArtifactError(
                "calibration observed model version is inconsistent"
            )
        if manifest.get("model_requested") != lock.get("model_requested"):
            raise CalibrationArtifactError(
                "calibration requested model is inconsistent"
            )
        required_ids = set(required_definition_ids or ())
        if not required_ids or not required_ids.issubset(question_ids):
            raise CalibrationArtifactError(
                "production lock omits its required definitions"
            )
    logger.info(
        "jevcal_upstream_artifact_validated lock=%s manifest=%s questions=%s status=%s",
        lock_path,
        manifest_path,
        len(question_ids),
        manifest.get("status"),
    )
    return CalibrationInputs(lock=lock, manifest=manifest)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise CalibrationArtifactError(
                    "calibration observation must be an object"
                )
            rows.append(value)
    return rows


def _questions_yaml(questions: dict[str, dict[str, object]], *, model: str) -> str:
    import yaml

    return yaml.safe_dump(
        {"model": model, "questions": questions}, allow_unicode=False, sort_keys=False
    )


def _required_string(row: dict[str, object], key: str) -> str:
    value = row.get(key)
    if not isinstance(value, str) or not value:
        raise CalibrationArtifactError(f"missing string field {key}")
    return value


def _probability(row: dict[str, object]) -> float:
    value = row.get("probability")
    if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
        raise CalibrationArtifactError(f"invalid probability: {row.get('case_id')}")
    return float(value)


def _probability_distribution(
    observation: dict[str, object], labels: tuple[str, ...]
) -> dict[str, float]:
    raw = observation.get("probabilities")
    if not isinstance(raw, dict) or set(raw) != set(labels):
        raise CalibrationArtifactError(
            f"full upstream probability distribution is required: {observation.get('case_id')}"
        )
    probabilities: dict[str, float] = {}
    for label, value in raw.items():
        if not isinstance(value, (int, float)) or not 0 <= float(value) <= 1:
            raise CalibrationArtifactError(
                f"invalid probability distribution: {observation.get('case_id')}"
            )
        probabilities[label] = float(value)
    if abs(sum(probabilities.values()) - 1.0) > 0.02:
        raise CalibrationArtifactError(
            f"probability distribution does not sum to one: {observation.get('case_id')}"
        )
    return probabilities


def _fixture_distribution(
    labels: tuple[str, ...], prediction: str, probability: float
) -> dict[str, float]:
    if len(labels) < 2 or prediction not in labels:
        raise CalibrationArtifactError("invalid fixture calibration choice labels")
    remainder = (1.0 - probability) / (len(labels) - 1)
    return {
        label: probability if label == prediction else remainder for label in labels
    }


def _optional_nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


def _hash_file(path: Path) -> str:
    # Git may check this JSONL text file out with CRLF on Windows. Normalize
    # record separators so the same calibration corpus keeps the same hash
    # across supported operating systems.
    content = path.read_bytes().replace(b"\r\n", b"\n")
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _hash_value(value: object) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _sample_counts(
    path: Path, definition_ids: list[str] | tuple[str, ...]
) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {}
    for row in _read_jsonl(path):
        definition_id = _required_string(row, "definition_id")
        if definition_id not in definition_ids:
            continue
        entry = counts.setdefault(definition_id, {"total": 0, "heldout": 0})
        entry["total"] += 1
        if row.get("split") == "heldout":
            entry["heldout"] += 1
    return counts


def _label_support(
    rows: tuple[dict[str, object], ...],
    labels_by_definition: dict[str, tuple[str, ...]],
) -> dict[str, dict[str, dict[str, int]]]:
    """Report source-corpus class support without fitting any local thresholds."""

    support: dict[str, dict[str, dict[str, int]]] = {
        definition_id: {label: {"total": 0, "heldout": 0} for label in labels}
        for definition_id, labels in labels_by_definition.items()
    }
    for row in rows:
        labels = row.get("labels")
        metadata = row.get("andromeda")
        if not isinstance(labels, dict) or not isinstance(metadata, dict):
            continue
        split = metadata.get("split")
        for definition_id, label in labels.items():
            if definition_id not in support or not isinstance(label, str) or not label:
                continue
            counts = support[definition_id].setdefault(
                label, {"total": 0, "heldout": 0}
            )
            counts["total"] += 1
            if split == "heldout":
                counts["heldout"] += 1
    return support


def _criterion_labels(bundle: object, definition_id: str) -> tuple[str, ...]:
    questions = getattr(bundle, "questions", None)
    question = questions.get(definition_id) if isinstance(questions, dict) else None
    criteria = question.get("criteria") if isinstance(question, dict) else None
    if not isinstance(criteria, dict) or any(
        not isinstance(label, str) or not label for label in criteria
    ):
        raise CalibrationArtifactError(
            f"jevcal question criteria are invalid: {definition_id}"
        )
    return tuple(criteria)


if __name__ == "__main__":
    raise SystemExit(main())
