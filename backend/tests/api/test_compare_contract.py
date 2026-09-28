from __future__ import annotations

from fastapi.testclient import TestClient

from andromeda.api.main import create_app


def test_compare_contract_exposes_both_programs(ingested_db: tuple[str, object, object]) -> None:
    database_url, _, _ = ingested_db
    response = TestClient(create_app(database_url)).get(
        "/compare?programIds=program:09.03.01-02,program:09.03.01-12"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["programA"]["code"] == "09.03.01-02"
    assert payload["programB"]["code"] == "09.03.01-12"
    assert all(row["status"] in {"both", "only_a", "only_b", "different"} for row in payload["rows"])


def test_compare_summary_is_additive_and_keeps_raw_route_unchanged(ingested_db: tuple[str, object, object]) -> None:
    database_url, _, _ = ingested_db
    client = TestClient(create_app(database_url))
    response = client.get(
        "/compare/summary",
        params={"programIds": "program:09.03.01-02,program:09.03.01-12"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert [program["program"]["id"] for program in payload["programs"]] == [
        "program:bmstu:09.03.01-02",
        "program:bmstu:09.03.01-12",
    ]
    assert "winner" not in payload
    assert "overallScore" not in payload
    assert all(difference["evidence"] for difference in payload["keyDifferences"])

    for invalid in (
        "program:09.03.01-02",
        "program:09.03.01-02,program:09.03.01-02",
        "program:09.03.01-02,program:09.03.01-12,program:09.03.01-13,program:09.03.01-14",
    ):
        assert client.get("/compare/summary", params={"programIds": invalid}).status_code == 422
