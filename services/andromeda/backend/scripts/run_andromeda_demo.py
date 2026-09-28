"""Canonical Andromeda fixture/live demo and production smoke runner."""

from __future__ import annotations

import argparse
from http.cookiejar import CookieJar
import hashlib
import hmac
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from subprocess import Popen
from typing import Sequence, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = REPO_ROOT / "backend"
FRONTEND_ROOT = REPO_ROOT / "frontend-next"
sys.path.insert(0, str(BACKEND_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from andromeda.ingestion.universities.bmstu import (  # noqa: E402
    DEFAULT_CAMPUS_FIXTURE_DIR,
    DEFAULT_EVENT_FIXTURE_DIR,
    DEFAULT_FIXTURE_DIR,
)
from andromeda.infrastructure.config import Settings  # noqa: E402
from andromeda.shared.contracts.ids import canonical_program_id  # noqa: E402
from run_andromeda_bmstu import (  # noqa: E402
    AndromedaRunResult,
    configure_logging,
    run_ingest,
    selected_program_codes,
)


logger = logging.getLogger("andromeda.demo")


class DemoError(RuntimeError):
    """Raised when a process or contract check fails during the demo."""


def default_database_url() -> str:
    environment_url = os.environ.get("ANDROMEDA_DATABASE_URL") or os.environ.get("BMSTU_DATABASE_URL")
    if environment_url is not None:
        return environment_url
    if os.environ.get("ANDROMEDA_ENV", "test").strip().lower() in {"development", "staging"}:
        return Settings.from_environment().database_url
    return "sqlite:///backend/data/andromeda-demo.db"


def resolve_database_url(database_url: str) -> str:
    """Make relative SQLite paths stable for ingestion and the child API process."""

    if not database_url.startswith("sqlite:///") or ":memory:" in database_url:
        return database_url
    raw_path = database_url.removeprefix("sqlite:///")
    database_path = Path(raw_path)
    if not database_path.is_absolute():
        base = REPO_ROOT if database_path.parts and database_path.parts[0] == "backend" else BACKEND_ROOT
        database_path = (base / database_path).resolve()
    return f"sqlite:///{database_path.as_posix()}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the complete Andromeda fixture/live demo")
    parser.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    parser.add_argument("--fixture-dir", type=Path, default=DEFAULT_FIXTURE_DIR)
    parser.add_argument("--event-fixture-dir", type=Path, default=DEFAULT_EVENT_FIXTURE_DIR)
    parser.add_argument("--campus-fixture-dir", type=Path, default=DEFAULT_CAMPUS_FIXTURE_DIR)
    parser.add_argument("--database-url", default=default_database_url())
    parser.add_argument("--program-code", action="append", dest="program_codes")
    parser.add_argument("--program-id", action="append", dest="program_ids")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=3000)
    parser.add_argument("--timeout", type=float, default=45.0)
    parser.add_argument("--check", action="store_true", help="verify readiness and exit instead of keeping servers alive")
    parser.add_argument("--log-level", choices=("DEBUG", "INFO", "WARNING", "ERROR"), default="INFO")
    return parser


def _http_get(url: str) -> bytes:
    request = Request(url, headers={"Accept": "application/json, text/html"})
    with urlopen(request, timeout=5.0) as response:
        if response.status != 200:
            raise DemoError(f"{url} returned HTTP {response.status}")
        return cast(bytes, response.read())


def wait_for_http(url: str, process: Popen[bytes], timeout: float, label: str) -> None:
    deadline = time.monotonic() + timeout
    last_error = "no response"
    while time.monotonic() < deadline:
        return_code = process.poll()
        if return_code is not None:
            raise DemoError(f"{label} exited before readiness with code {return_code}")
        try:
            _http_get(url)
            logger.info("stage_ready name=%s url=%s", label, url)
            return
        except (DemoError, HTTPError, URLError, OSError, TimeoutError) as exc:
            last_error = str(exc)
            time.sleep(0.25)
    raise DemoError(f"Timed out waiting for {label} at {url}: {last_error}")


def _json_object(body: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DemoError(f"{label} did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise DemoError(f"{label} did not return a JSON object")
    return value


def discover_program_codes(api_base_url: str) -> tuple[str, ...]:
    """Read verification candidates from the ingested catalog, never constants."""

    payload = _json_object(_http_get(f"{api_base_url}/programs"), "program catalog endpoint")
    items = payload.get("items")
    if not isinstance(items, list):
        raise DemoError("program catalog response does not contain an item list")
    codes = tuple(
        item["id"]
        for item in items
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item["id"]
    )
    if len(codes) < 2:
        raise DemoError("program catalog contains fewer than two programs for comparison")
    logger.info("stage_verified name=catalog programs=%d", len(codes))
    return codes


def verify_compare(api_base_url: str, program_codes: Sequence[str]) -> None:
    if len(program_codes) != 2:
        raise DemoError("the Andromeda demo requires exactly two program codes")
    program_ids = tuple(_verification_program_id(value) for value in program_codes)
    query = quote(",".join(program_ids), safe="")
    payload = _json_object(_http_get(f"{api_base_url}/compare?programIds={query}"), "compare endpoint")
    for key, expected_id in zip(("programA", "programB"), program_ids):
        program = payload.get(key)
        if not isinstance(program, dict) or program.get("id") != expected_id:
            raise DemoError(f"compare response has an invalid {key}")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise DemoError("compare response contains no curriculum rows")
    logger.info("stage_verified name=compare programs=%s rows=%d", ",".join(program_ids), len(rows))


def verify_og(frontend_url: str, program_codes: Sequence[str], secret: str) -> None:
    """Smoke-test signed Next OG routes without external credentials or a browser."""

    program_ids = tuple(_verification_program_id(value) for value in program_codes[:2])
    checks = (
        ("/og/program", {"ids": program_ids[0]}),
        ("/og/compare", {"ids": ",".join(program_ids)}),
        ("/og/shortlist", {}),
        ("/og/chances", {}),
        ("/og/radar", {"ids": ",".join(program_ids)}),
        ("/og/curriculum", {"ids": ",".join(program_ids)}),
        ("/og/digest", {}),
    )
    for path, params in checks:
        query = urlencode(sorted(params.items()))
        timestamp = str(int(time.time()))
        message = f"GET\n{path}\n{query}\n{timestamp}".encode("utf-8")
        signature = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
        request = Request(
            f"{frontend_url.rstrip('/')}{path}{'?' + query if query else ''}",
            headers={
                "Accept": "image/png",
                "X-Andromeda-Render-Timestamp": timestamp,
                "X-Andromeda-Render-Signature": signature,
            },
        )
        with urlopen(request, timeout=15.0) as response:
            body = cast(bytes, response.read())
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if response.status != 200 or content_type != "image/png" or not body.startswith(b"\x89PNG\r\n\x1a\n"):
                raise DemoError(f"{path} did not return a signed PNG")
    logger.info("stage_verified name=og_routes routes=%d", len(checks))


def verify_admissions(api_base_url: str, program_codes: Sequence[str]) -> None:
    """Verify that admissions projection is reachable through the public API."""

    for code in program_codes:
        program_id = _verification_program_id(code)
        payload = _json_object(
            _http_get(f"{api_base_url}/programs/{quote(program_id, safe='')}/admissions"),
            "admissions endpoint",
        )
        if payload.get("programId") != program_id:
            raise DemoError(f"admissions response has an invalid program id for {program_id}")
        offerings = payload.get("offerings")
        if not isinstance(offerings, list) or not offerings:
            raise DemoError(f"admissions response contains no offerings for {program_id}")
        if not all(isinstance(item, dict) and item.get("provenance") for item in offerings):
            raise DemoError(f"admissions response has an offering without provenance for {program_id}")
        logger.info("stage_verified name=admissions program=%s offerings=%d", program_id, len(offerings))


def verify_events(api_base_url: str, expected_event_count: int = 5) -> None:
    """Verify event projection, provenance, links, and recommendation filtering."""

    payload = _json_object(_http_get(f"{api_base_url}/events"), "events endpoint")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) < expected_event_count:
        raise DemoError(f"events response contains fewer than {expected_event_count} fixture events")
    if payload.get("total", 0) < expected_event_count:
        raise DemoError("events response total is smaller than the fixture count")
    for item in items:
        if not isinstance(item, dict) or not str(item.get("id", "")).startswith("event:bmstu:"):
            raise DemoError("events response has an invalid canonical event id")
        provenance = item.get("provenance")
        first_provenance = provenance[0] if isinstance(provenance, list) and provenance else None
        if not isinstance(first_provenance, dict) or first_provenance.get("kind") != "bmstu_events":
            raise DemoError("events response has missing BMSTU provenance")
        program_ids = item.get("programIds", [])
        if not isinstance(program_ids, list):
            raise DemoError("events response has invalid program links")
        for program_id in program_ids:
            if not isinstance(program_id, str) or not program_id.startswith("program:"):
                raise DemoError("events response has a non-canonical program link")
    logger.info("stage_verified name=events count=%d", len(items))

    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    request = Request(
        f"{api_base_url}/proftest/results",
        data=json.dumps(
            {
                "answers": [
                    {"questionId": "interest_free_day", "optionIds": ["software_tool"]},
                    {"questionId": "interest_investigation", "optionIds": ["prove_model"]},
                    {"questionId": "activity_build", "optionIds": ["system_scheme"]},
                    {"questionId": "activity_working_style", "optionIds": ["analyze_options"]},
                    {"questionId": "anti_subjects", "optionIds": ["avoid_physics"], "intensity": 0.9},
                    {"questionId": "activity_depth", "optionIds": ["practical_prototype"]},
                ]
            }
        ).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(request, timeout=5.0) as response:
        if response.status != 200:
            raise DemoError("profile creation failed during events verification")
        recommendations = _json_object(response.read(), "profile result endpoint").get("recommendations")
    if not isinstance(recommendations, list) or not recommendations:
        raise DemoError("profile creation returned no recommendations for events verification")
    recommended_ids = {item.get("programId") for item in recommendations if isinstance(item, dict)}
    with opener.open(Request(f"{api_base_url}/events?recommended=true", headers={"Accept": "application/json"}), timeout=5.0) as response:
        if response.status != 200:
            raise DemoError("recommended events query failed after profile creation")
        recommended_payload = _json_object(response.read(), "recommended events endpoint")
    recommended_items = recommended_payload.get("items")
    if not isinstance(recommended_items, list):
        raise DemoError("recommended events response does not contain an item list")
    for item in recommended_items:
        if not isinstance(item, dict) or not isinstance(item.get("programIds"), list) or not (set(item["programIds"]) & recommended_ids):
            raise DemoError("recommended events response contains an event without recommendation evidence")
    if not recommended_items and recommended_ids:
        logger.warning("stage_verified name=events_recommended count=0 recommendation_count=%d", len(recommended_ids))
    if any(item.get("id") == "event:bmstu:research-day-2026" for item in recommended_items if isinstance(item, dict)):
        raise DemoError("unlinked university event was returned by recommended filter")
    logger.info("stage_verified name=events_recommended count=%d recommendation_count=%d", len(recommended_items), len(recommended_ids))


def _verification_program_id(value: str) -> str:
    return canonical_program_id(value if value.startswith("program:") else f"program:{value}")


def verify_campus_data(api_base_url: str, expected_point_count: int = 5, program_id: str | None = None) -> None:
    """Verify the external-consumer campus contract without exercising map UI."""

    logger.info("stage_start name=campus_data")
    payload = _json_object(_http_get(f"{api_base_url}/campus/points?limit=100"), "campus points endpoint")
    items = payload.get("items")
    if not isinstance(items, list) or len(items) < expected_point_count:
        raise DemoError(f"campus response contains fewer than {expected_point_count} fixture points")
    if payload.get("total", 0) < expected_point_count:
        raise DemoError("campus response total is smaller than the fixture point count")
    for item in items:
        if not isinstance(item, dict) or not str(item.get("id", "")).startswith("venue:bmstu:"):
            raise DemoError("campus response has an invalid canonical point id")
        if item.get("pointType") not in {"building", "room_zone", "event_venue", "entrance", "other"}:
            raise DemoError("campus response has an invalid point type")
        provenance = item.get("provenance")
        first_provenance = provenance[0] if isinstance(provenance, list) and provenance else None
        if not isinstance(first_provenance, dict) or first_provenance.get("kind") != "bmstu_campus_points":
            raise DemoError("campus response has missing campus provenance")
    logger.info("stage_verified name=campus_points count=%d", len(items))

    point_id = next(
        (
            item["id"]
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("eventCount"), int)
            and item["eventCount"] > 0
        ),
        None,
    )
    if point_id is None:
        point_id = next((item["id"] for item in items if isinstance(item, dict) and isinstance(item.get("id"), str)), None)
    if point_id is None:
        raise DemoError("campus response contains no point ID")
    detail = _json_object(_http_get(f"{api_base_url}/campus/points/{quote(point_id, safe='')}"), "campus point detail endpoint")
    if detail.get("id") != point_id or not isinstance(detail.get("universityIds"), list):
        raise DemoError("campus point detail is missing card references")
    point_events = _json_object(
        _http_get(f"{api_base_url}/campus/points/{quote(point_id, safe='')}/events"),
        "campus point events endpoint",
    )
    point_event_items = point_events.get("items")
    if not isinstance(point_event_items, list) or not point_event_items:
        raise DemoError("campus point events response is empty")
    logger.info("stage_verified name=campus_point_detail point_id=%s events=%d", point_id, len(point_event_items))

    if program_id is not None:
        program_query = urlencode({"programId": program_id, "limit": 100})
        program_payload = _json_object(_http_get(f"{api_base_url}/campus/points?{program_query}"), "campus program filter endpoint")
        program_items = program_payload.get("items")
        if not isinstance(program_items, list) or not program_items:
            raise DemoError("campus program filter returned no points")
        logger.info("stage_verified name=campus_filters program_count=%d", len(program_items))

    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    request = Request(
        f"{api_base_url}/proftest/results",
        data=json.dumps(
            {
                "answers": [
                    {"questionId": "interest_free_day", "optionIds": ["software_tool"]},
                    {"questionId": "interest_investigation", "optionIds": ["prove_model"]},
                    {"questionId": "activity_build", "optionIds": ["system_scheme"]},
                    {"questionId": "activity_working_style", "optionIds": ["analyze_options"]},
                    {"questionId": "anti_subjects", "optionIds": ["avoid_physics"], "intensity": 0.9},
                    {"questionId": "activity_depth", "optionIds": ["practical_prototype"]},
                ]
            }
        ).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="POST",
    )
    with opener.open(request, timeout=5.0) as response:
        if response.status != 200:
            raise DemoError("profile creation failed during campus verification")
    with opener.open(Request(f"{api_base_url}/campus/recommendations", headers={"Accept": "application/json"}), timeout=5.0) as response:
        if response.status != 200:
            raise DemoError("recommended campus query failed after profile creation")
        recommendation_payload = _json_object(response.read(), "recommended campus endpoint")
    recommended_ids = recommendation_payload.get("recommendedProgramIds")
    recommended_points = recommendation_payload.get("points")
    recommended_events = recommendation_payload.get("events")
    unplaced_events = recommendation_payload.get("eventsWithoutPoint")
    if not isinstance(recommended_ids, list) or not recommended_ids:
        raise DemoError("recommended campus response contains no recommended programs")
    if not isinstance(recommended_points, list) or not isinstance(recommended_events, list) or not isinstance(unplaced_events, list):
        raise DemoError("recommended campus response has an invalid data envelope")
    for item in recommended_points:
        if not isinstance(item, dict) or not (set(item.get("programIds", [])) & set(recommended_ids)):
            raise DemoError("recommended campus response contains a point without program intersection")
    for item in recommended_events:
        if not isinstance(item, dict) or not isinstance(item.get("programIds"), list) or not (set(item["programIds"]) & set(recommended_ids)):
            raise DemoError("recommended campus response contains an event without program intersection")
        if not isinstance(item.get("venue"), dict):
            raise DemoError("recommended campus physical event is missing a venue")
    for item in unplaced_events:
        if not isinstance(item, dict) or item.get("venue") is not None:
            raise DemoError("unplaced campus event unexpectedly contains a venue")
    logger.info(
        "stage_verified name=campus_recommended points=%d events=%d unplaced_events=%d recommendation_count=%d",
        len(recommended_points),
        len(recommended_events),
        len(unplaced_events),
        len(recommended_ids),
    )


def _start_process(command: list[str], cwd: Path, env: dict[str, str], label: str) -> Popen[bytes]:
    logger.info("stage_start name=%s command=%s", label, " ".join(command))
    if os.name == "nt":
        return subprocess.Popen(command, cwd=cwd, env=env, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(command, cwd=cwd, env=env, start_new_session=True)


def _stop_process(process: Popen[bytes], label: str) -> None:
    if process.poll() is not None:
        return
    logger.info("stage_stop name=%s", label)
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    else:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)  # type: ignore[attr-defined]
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        logger.warning("stage_kill name=%s", label)
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)  # type: ignore[attr-defined]
        process.wait(timeout=10)


def run_demo(args: argparse.Namespace) -> AndromedaRunResult:
    program_codes = selected_program_codes(args.program_codes, args.program_ids)
    database_url = resolve_database_url(args.database_url)
    fixture_dir = args.fixture_dir if args.fixture_dir.is_absolute() else (REPO_ROOT / args.fixture_dir).resolve()
    configured_event_fixture_dir = getattr(args, "event_fixture_dir", DEFAULT_EVENT_FIXTURE_DIR)
    event_fixture_dir = configured_event_fixture_dir if configured_event_fixture_dir.is_absolute() else (REPO_ROOT / configured_event_fixture_dir).resolve()
    configured_campus_fixture_dir = getattr(args, "campus_fixture_dir", DEFAULT_CAMPUS_FIXTURE_DIR)
    campus_fixture_dir = configured_campus_fixture_dir if configured_campus_fixture_dir.is_absolute() else (REPO_ROOT / configured_campus_fixture_dir).resolve()
    result = run_ingest(
        mode=args.mode,
        fixture_dir=fixture_dir,
        event_fixture_dir=event_fixture_dir,
        campus_fixture_dir=campus_fixture_dir,
        database_url=database_url,
        program_codes=program_codes or None,
    )
    logger.info(
        "stage_complete name=database run_id=%s items=%d events=%d campus_points=%d",
        result.run_id,
        result.curriculum_item_count,
        result.event_count,
        result.campus_point_count,
    )

    child_env = os.environ.copy()
    child_env["ANDROMEDA_DATABASE_URL"] = database_url
    child_env["PYTHONPATH"] = os.pathsep.join(value for value in (str(BACKEND_ROOT / "src"), child_env.get("PYTHONPATH")) if value)
    api_base_url = f"http://{args.host}:{args.api_port}"
    frontend_url = f"http://{args.host}:{args.frontend_port}/"
    frontend_origins = dict.fromkeys(
        (
            f"http://{args.host}:{args.frontend_port}",
            f"http://127.0.0.1:{args.frontend_port}",
            f"http://localhost:{args.frontend_port}",
        )
    )
    child_env["FRONTEND_ORIGIN"] = ",".join(frontend_origins)
    child_env["NEXT_PUBLIC_API_BASE_URL"] = api_base_url
    child_env["NEXT_PUBLIC_DEBUG_API"] = "0"
    child_env["ANDROMEDA_RENDER_HMAC_SECRET"] = "ci-og-secret"
    child_env["ANDROMEDA_INTERNAL_API_URL"] = api_base_url
    child_env["NEXT_TELEMETRY_DISABLED"] = "1"
    api_process: Popen[bytes] | None = None
    frontend_process: Popen[bytes] | None = None
    try:
        api_process = _start_process(
            [sys.executable, "-m", "uvicorn", "andromeda.api.main:app", "--host", args.host, "--port", str(args.api_port)],
            REPO_ROOT,
            child_env,
            "api",
        )
        frontend_executable = "npm.cmd" if os.name == "nt" else "npm"
        frontend_process = _start_process(
            [frontend_executable, "run", "dev", "--", "--hostname", args.host, "--port", str(args.frontend_port)],
            FRONTEND_ROOT,
            child_env,
            "frontend",
        )
        wait_for_http(f"{api_base_url}/openapi.json", api_process, args.timeout, "api")
        wait_for_http(frontend_url, frontend_process, args.timeout, "frontend")
        discovered_codes = discover_program_codes(api_base_url)
        verification_codes = tuple(_verification_program_id(value) for value in (program_codes or discovered_codes[:2]))
        verify_compare(api_base_url, verification_codes)
        verify_og(frontend_url, verification_codes, child_env["ANDROMEDA_RENDER_HMAC_SECRET"])
        verify_admissions(api_base_url, verification_codes)
        verify_events(api_base_url, result.event_count)
        verify_campus_data(api_base_url, result.campus_point_count, program_id=verification_codes[0])
        if not args.check:
            logger.info("demo_ready api=%s frontend=%s; press Ctrl-C to stop", api_base_url, frontend_url)
            while True:
                if api_process.poll() is not None:
                    raise DemoError("api exited while demo was running")
                if frontend_process.poll() is not None:
                    raise DemoError("frontend exited while demo was running")
                time.sleep(1.0)
        return result
    finally:
        if frontend_process is not None:
            _stop_process(frontend_process, "frontend")
        if api_process is not None:
            _stop_process(api_process, "api")


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(args.log_level)
    try:
        result = run_demo(args)
    except KeyboardInterrupt:
        logger.info("demo_stopped_by_user")
        return 0
    except (DemoError, ValueError, OSError) as exc:
        logger.error("demo_failed error=%s", exc)
        return 1
    print(
        json.dumps(
            {
                "runId": result.run_id,
                "programIds": list(result.program_ids),
                "curriculumItemCount": result.curriculum_item_count,
                "sourceCount": result.source_count,
                "sourceHashes": list(result.source_hashes),
                "eventCount": result.event_count,
                "campusPointCount": result.campus_point_count,
                "mode": args.mode,
                "check": args.check,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DemoError",
    "build_parser",
    "default_database_url",
    "discover_program_codes",
    "main",
    "resolve_database_url",
    "run_demo",
    "verify_admissions",
    "verify_campus_data",
    "verify_compare",
    "verify_events",
    "verify_og",
    "wait_for_http",
]
