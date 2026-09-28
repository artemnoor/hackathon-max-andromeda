from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from .contracts.normalized import CanonicalSnapshot
from .contracts.raw import RawSourceSnapshot, RawTracerBundle
from .contracts.source import CapturedSources


class SourceAdapter(Protocol):
    """Adapter contract implemented by each university ingestion module."""

    def capture(self, mode: str = "fixture", fixture_dir: Path | None = None) -> CapturedSources: ...

    def parse(
        self,
        captured: CapturedSources,
        program_codes: Sequence[str] | None = None,
    ) -> tuple[RawTracerBundle, CanonicalSnapshot]: ...


class SourceCaptureAuditWriter(Protocol):
    """Capture-only audit operations implemented by the shared ingestion adapter."""

    def start_run(
        self,
        run_id: str | None = None,
        *,
        source_profile: str = "legacy",
        source_revision: str = "legacy",
        configuration_version: str = "legacy",
        university_id: str = "university:legacy",
        projection_target: str = "canonical",
        idempotency_key: str | None = None,
    ) -> str: ...

    def record_staged_source_snapshots(
        self, run_id: str, snapshots: tuple[RawSourceSnapshot, ...]
    ) -> None: ...

    def finish_source_capture_run(self, run_id: str) -> None: ...

    def mark_failed(self, run_id: str, error: Exception) -> None: ...
