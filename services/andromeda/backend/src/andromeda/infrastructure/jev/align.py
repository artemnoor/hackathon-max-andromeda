"""Thin integration boundary around the pinned upstream ``jev-align`` runtime.

The semantic module owns proposals and human approval.  This adapter owns only
the upstream active-learning session used to select uncertain examples and run
GEPA optimization.  It deliberately does not publish a semantic artifact:
publication remains an explicit Andromeda review transition.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast


@dataclass(frozen=True)
class JevAlignStoryInput:
    """A source-backed semantic example presented to the upstream evaluator."""

    story_id: str
    fields: dict[str, str]


@dataclass(frozen=True)
class JevAlignConfig:
    """Runtime settings passed to upstream ``jev-align`` without vendor leakage."""

    run_directory: Path
    task_instructions: str
    feature_criteria: dict[str, tuple[str, str]]
    model: str = "jev-1.13.0"
    reflection_model: str = "jev-1.13.0"
    metric_budget: int = 300
    concurrency: int = 1
    batch_size: int = 5
    seed: int = 0


class JevAlignSession:
    """Andromeda-owned handle over a real upstream ``ClimbSession``.

    The import is lazy because jev-align is an evaluation-only dependency.  A
    production canonical ingestion process can therefore run without it.
    """

    def __init__(self, session: Any) -> None:
        self._session = session

    @property
    def upstream_session(self) -> Any:
        """Expose the upstream session for CLI/evaluation adapters only."""

        return self._session

    @classmethod
    def create(
        cls,
        stories: tuple[JevAlignStoryInput, ...],
        *,
        config: JevAlignConfig,
        backend: Any,
    ) -> JevAlignSession:
        if not stories:
            raise ValueError("jev-align requires at least one source-backed story")
        if not config.feature_criteria:
            raise ValueError("jev-align requires at least one semantic feature")
        if config.batch_size < 1 or config.concurrency < 1:
            raise ValueError("jev-align batch size and concurrency must be positive")

        from jev_align.models import (  # type: ignore[import-untyped]
            BackendConfig,
            CandidateHistory,
            MultilabelCriteria,
            MultilabelTaskSpec,
            RunState,
            Story,
        )
        from jev_align.persistence import RunStore  # type: ignore[import-untyped]
        from jev_align.session import ClimbSession  # type: ignore[import-untyped]

        run_directory = config.run_directory.expanduser().resolve()
        if run_directory.exists():
            raise ValueError(f"jev-align run directory already exists: {run_directory}")
        upstream_stories = [
            Story(id=item.story_id, row_number=index, fields=dict(item.fields))
            for index, item in enumerate(stories, start=1)
        ]
        source_payload = "".join(
            json.dumps(item.fields, ensure_ascii=False, sort_keys=True) + "\n"
            for item in upstream_stories
        ).encode("utf-8")
        source_path = run_directory / "source.jsonl"
        stories_path = run_directory / "stories.jsonl"
        candidate = MultilabelTaskSpec(
            instructions=config.task_instructions,
            labels={
                feature_id: MultilabelCriteria(
                    true_criteria=true_criteria,
                    false_criteria=false_criteria,
                )
                for feature_id, (true_criteria, false_criteria) in config.feature_criteria.items()
            },
        )
        state = RunState(
            run_id=run_directory.name,
            source_path=str(source_path),
            source_sha256=hashlib.sha256(source_payload).hexdigest(),
            selected_columns=list(upstream_stories[0].fields),
            column_mode="selected",
            pool_size=len(upstream_stories),
            seed=config.seed,
            backend=BackendConfig(provider="typesafe", model=config.model),
            reflection_model=config.reflection_model,
            metric_budget=config.metric_budget,
            concurrency=config.concurrency,
            batch_size=min(config.batch_size, len(upstream_stories)),
            holdout_fraction=0.0,
            current_candidate=candidate,
            history=[CandidateHistory(round_number=0, candidate=candidate, decision="seed")],
        )
        store = RunStore(run_directory)
        store.initialize(state)
        source_path.write_bytes(source_payload)
        stories_path.write_text(
            "".join(
                json.dumps(
                    {"id": item.id, "row_number": item.row_number, "fields": item.fields},
                    ensure_ascii=False,
                    sort_keys=True,
                )
                + "\n"
                for item in upstream_stories
            ),
            encoding="utf-8",
        )
        session = ClimbSession(state, upstream_stories, store, backend)
        return cls(session)

    @classmethod
    def open(cls, run_directory: Path, *, backend: Any) -> JevAlignSession:
        """Resume an existing upstream run for label/optimize/decision commands."""

        from jev_align.models import RunState, Story
        from jev_align.persistence import RunStore
        from jev_align.session import ClimbSession

        directory = run_directory.expanduser().resolve()
        store = RunStore(directory)
        state = store.load_state()
        stories_path = directory / "stories.jsonl"
        if not stories_path.exists():
            raise ValueError("jev-align run is missing the Andromeda story snapshot")
        stories = [
            Story.model_validate(json.loads(line))
            for line in stories_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not stories:
            raise ValueError("jev-align run contains no stories")
        state = RunState.model_validate(state.model_dump())
        return cls(ClimbSession(state, stories, store, backend))

    def acquire(self) -> tuple[list[Any], list[Any]]:
        """Use upstream uncertainty/exploration acquisition, not a local ranking."""

        return cast(tuple[list[Any], list[Any]], self._session.acquire())

    def add_label(
        self,
        *,
        story_id: str,
        label: list[str],
        rationale: str | None,
        acquired_by: Literal["ambiguous", "exploration", "holdout"],
        probability: float,
    ) -> Any:
        return self._session.add_label(
            story_id=story_id,
            label=label,
            rationale=rationale,
            acquired_by=acquired_by,
            probability=probability,
        )

    def optimize(self) -> Any:
        """Delegate GEPA optimization to upstream ``ClimbSession.optimize``."""

        predictions = self._session.current_pool_predictions()
        return self._session.optimize(predictions)

    def decide(self, decision: Literal["accept", "reject"]) -> None:
        """Record upstream candidate decision; semantic publication stays separate."""

        self._session.decide(decision)


def create_typesafe_backend(*, model: str, concurrency: int) -> Any:
    """Construct the real jev-align TypeSafe backend through its public API."""

    from jev_align.models import BackendConfig
    from jev_align.runtime import create_backend  # type: ignore[import-untyped]

    return create_backend(BackendConfig(provider="typesafe", model=model), concurrency=concurrency)


__all__ = ["JevAlignConfig", "JevAlignSession", "JevAlignStoryInput", "create_typesafe_backend"]
