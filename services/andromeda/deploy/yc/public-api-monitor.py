#!/usr/bin/env python3
"""Low-cost HTTPS smoke monitor for the public Andromeda API contract."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


BASE_URL = os.environ.get("PUBLIC_API_BASE_URL", "https://max.code-slicer.ru").rstrip("/")
TIMEOUT_SECONDS = 10


def get_json(path: str) -> object:
    request = Request(f"{BASE_URL}{path}", headers={"Accept": "application/json"})
    with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise RuntimeError(f"{path}: unexpected HTTP {response.status}")
        if "application/json" not in response.headers.get("Content-Type", ""):
            raise RuntimeError(f"{path}: unexpected content type")
        return json.load(response)


def require_object(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise RuntimeError(f"{path}: expected JSON object")
    return value


def main() -> int:
    try:
        health = require_object(get_json("/api/v1/health/live"), "/api/v1/health/live")
        if health.get("status") != "live":
            raise RuntimeError("liveness endpoint did not report live")

        programs = require_object(get_json("/api/v1/programs"), "/api/v1/programs")
        if not isinstance(programs.get("items"), list) or not programs["items"]:
            raise RuntimeError("program catalog is empty or has an invalid shape")

        openapi = require_object(get_json("/openapi.json"), "/openapi.json")
        if openapi.get("openapi") != "3.1.0":
            raise RuntimeError("published OpenAPI document is not version 3.1.0")
        paths = openapi.get("paths")
        if not isinstance(paths, dict) or "/api/v1/programs" not in paths:
            raise RuntimeError("published OpenAPI document is missing the public programs route")
        if any(not path.startswith("/api/v1/") for path in paths):
            raise RuntimeError("published OpenAPI document contains non-public routes")

        print(
            f"OK {datetime.now(timezone.utc).isoformat()} "
            f"programs={len(programs['items'])} openapi_paths={len(paths)}"
        )
        return 0
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        print(f"FAIL {datetime.now(timezone.utc).isoformat()} {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
