"""Replay the versioned decision corpus and emit aggregate-safe JSON."""

from __future__ import annotations

import json
from pathlib import Path

from andromeda.modules.conversation.contracts.evaluation import EvaluationCase
from andromeda.modules.conversation.services.evaluation import DecisionModelEvaluator


def main() -> None:
    root = Path(__file__).parents[1]
    corpus_path = root / "tests" / "fixtures" / "evaluation" / "decision-corpus-v1.json"
    payload = json.loads(corpus_path.read_text(encoding="utf-8"))
    cases = tuple(EvaluationCase.model_validate(item, strict=False) for item in payload["cases"])
    report = DecisionModelEvaluator(corpus_version=str(payload["corpus_version"])).evaluate(cases)
    print(report.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
