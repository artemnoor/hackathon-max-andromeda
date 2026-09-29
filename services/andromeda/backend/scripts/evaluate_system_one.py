"""Opt-in evaluation runner for the official System One adapter."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from andromeda.infrastructure.jev.question_registry import QuestionRegistry
from evals.jev.system_one_evaluator import (
    OfficialSystemOneQuestionFactory,
    SystemOneEvaluationCase,
    SystemOneEvaluator,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run opt-in System One evaluation; never used by production runtime")
    parser.add_argument("--provider", choices=("openai", "anthropic"), required=True)
    parser.add_argument("--model", required=True, help="provider model identifier")
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--allow-failures", action="store_true")
    args = parser.parse_args(argv)

    key_name = "OPENAI_API_KEY" if args.provider == "openai" else "ANTHROPIC_API_KEY"
    if not os.getenv(key_name):
        parser.error(f"{key_name} is required for opt-in provider evaluation")
    try:
        from system_one_adapter import SystemOneAdapterClient
    except ImportError as exc:
        parser.error("install backend[evaluation] before running System One evaluation")
        raise AssertionError from exc

    registry = QuestionRegistry.from_file(ROOT / "config" / "jev" / "question-definitions.v1.yaml")
    cases = _load_cases(registry, set(args.case_id))
    client = SystemOneAdapterClient(structured_outputs=True, llm_answer_mode="probabilities")
    try:
        rows = SystemOneEvaluator(client, OfficialSystemOneQuestionFactory()).evaluate(
            cases,
            provider=args.provider,
            model=args.model,
            allow_failures=args.allow_failures,
        )
    finally:
        close = getattr(client, "close", None)
        if callable(close):
            close()
    print(json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2, default=str))
    return 0


def _load_cases(registry: QuestionRegistry, selected: set[str]) -> tuple[SystemOneEvaluationCase, ...]:
    cases: list[SystemOneEvaluationCase] = []
    path = ROOT / "evals" / "jev" / "corpus" / "decision-cases.v1.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        if selected and row["case_id"] not in selected:
            continue
        definition = registry.get(row["definition_id"])
        input_data = row["input"]
        if not isinstance(input_data, dict) or not isinstance(input_data.get("text"), str):
            # System One is intentionally opt-in only for text cases until a
            # typed question builder exists for the remaining input shapes.
            continue
        cases.append(
            SystemOneEvaluationCase(
                case_id=row["case_id"],
                definition=definition,
                input_text=input_data["text"],
                expected=row["expected"],
                input_data=input_data,
            )
        )
    return tuple(cases)


if __name__ == "__main__":
    raise SystemExit(main())
