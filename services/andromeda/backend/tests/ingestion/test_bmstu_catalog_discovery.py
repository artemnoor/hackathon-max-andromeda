from __future__ import annotations

import json

from andromeda.ingestion.universities.bmstu.parser.catalog import select_catalog_programs
from andromeda.ingestion.universities.bmstu.capture import _catalog_page


def test_catalog_parser_accepts_paginated_api_shape_and_preserves_all_cards() -> None:
    payload = {
        "data": [
            {"code": "09.03.01", "name": "Информатика", "slug": "informatika"},
            {"code": "24.05.01", "name": "Проектирование", "slug": "proektirovanie"},
        ],
        "meta": {"count": 2, "limit": 1, "offset": 0},
    }

    cards, total = _catalog_page(json.dumps(payload).encode())
    assert total == 2
    assert [card["code"] for card in cards] == ["09.03.01", "24.05.01"]
    assert [card["slug"] for card in cards] == ["informatika", "proektirovanie"]


def test_catalog_selection_has_no_implicit_program_scope() -> None:
    assert select_catalog_programs() == ()
    assert select_catalog_programs(("09.03.01-02", "09.03.01-12")) == (
        "09.03.01-02",
        "09.03.01-12",
    )
