from __future__ import annotations

import json
from collections.abc import Sequence
from typing import cast

from andromeda.ingestion.contracts.raw import RawSourceSnapshot

from ..identity import direction_codes
from ..selectors import select_program_codes


def select_catalog_programs(values: Sequence[str] | None = None) -> tuple[str, ...]:
    # ``None`` is the explicit adapter signal for live catalog discovery.
    # A caller that supplies codes still gets the strict selector contract.
    return () if values is None else select_program_codes(tuple(values))


def parse_catalog_direction_codes(snapshots: Sequence[RawSourceSnapshot]) -> frozenset[str]:
    """Extract direction identities from official BMSTU catalog JSON snapshots.

    The adapter may intentionally import only a selected program subset (for
    example in a fixture or an incremental run), while admission-benefit
    scopes still need the complete catalog identity set to resolve ``ALL
    EXCEPT``/``ONLY`` targets.  This helper reads only the source catalog's
    explicit ``data[].code`` values; it does not manufacture canonical
    programs or infer identities from names.
    """

    result: set[str] = set()
    for snapshot in snapshots:
        try:
            payload = json.loads(snapshot.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            continue
        for item in cast(list[object], payload["data"]):
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            if isinstance(code, str):
                result.update(direction_codes(code))
    return frozenset(result)


def parse_catalog_direction_index(snapshots: Sequence[RawSourceSnapshot]) -> dict[str, str]:
    """Index explicit catalog direction names by their canonical code."""

    result: dict[str, str] = {}
    for snapshot in snapshots:
        try:
            payload = json.loads(snapshot.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
            continue
        for item in payload["data"]:
            if not isinstance(item, dict):
                continue
            code = item.get("code")
            name = item.get("name")
            if not isinstance(code, str) or not isinstance(name, str):
                continue
            codes = tuple(direction_codes(code))
            if len(codes) != 1:
                continue
            result[_normalize_catalog_name(name)] = codes[0]
    return result


def _normalize_catalog_name(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


__all__ = ["parse_catalog_direction_codes", "parse_catalog_direction_index", "select_catalog_programs"]
