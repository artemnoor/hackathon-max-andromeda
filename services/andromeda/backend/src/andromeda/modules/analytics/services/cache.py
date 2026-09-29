"""Small process-local cache for immutable analytics results."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass

from ..contracts.results import AnalyticsResult


@dataclass(frozen=True, slots=True)
class _Entry:
    result: AnalyticsResult
    program_ids: frozenset[str]


class AnalyticsResultCache:
    """Bounded cache invalidated by affected materialized program IDs."""

    def __init__(self, *, max_entries: int = 256) -> None:
        if max_entries < 1:
            raise ValueError("analytics cache must allow at least one entry")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, _Entry] = OrderedDict()

    def get(self, key: str) -> AnalyticsResult | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        self._entries.move_to_end(key)
        return entry.result

    def put(self, key: str, result: AnalyticsResult, *, program_ids: frozenset[str]) -> None:
        self._entries[key] = _Entry(result=result, program_ids=program_ids)
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)

    def invalidate(self, program_ids: Iterable[str]) -> None:
        program_ids = frozenset(program_ids)
        if not program_ids:
            return
        for key, entry in tuple(self._entries.items()):
            if entry.program_ids.intersection(program_ids):
                del self._entries[key]

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


__all__ = ["AnalyticsResultCache"]
