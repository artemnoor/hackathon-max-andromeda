from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256

import pytest

from andromeda.ingestion.contracts.source import CapturedSources, RawSourceSnapshot
from andromeda.shared.contracts.errors import ContractError


def _snapshot(kind: str) -> RawSourceSnapshot:
    body = kind.encode()
    return RawSourceSnapshot(
        source_kind=kind,
        requested_url="https://bmstu.ru/",
        final_url="https://bmstu.ru/",
        status_code=200,
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        content_sha256=sha256(body).hexdigest(),
        body=body,
    )


def test_source_selection_fails_closed_for_duplicate_kinds() -> None:
    captured = CapturedSources((_snapshot("bmstu_common"), _snapshot("bmstu_common")))
    with pytest.raises(ContractError):
        captured.first("bmstu_common")
