from __future__ import annotations

import httpx
import pytest

from andromeda.ingestion.fetch_policy import SourcePolicyError, validate_source_url
from andromeda.ingestion.universities.bmstu.fetch import (
    BMSTU_SOURCE_HOST_POLICY,
    FetchConfig,
    Fetcher,
)


def _public_resolver(host: str) -> tuple[str, ...]:
    del host
    return ("8.8.8.8",)


def test_private_target_is_rejected_before_transport() -> None:
    with pytest.raises(SourcePolicyError, match="non-public"):
        validate_source_url("https://bmstu.ru/", BMSTU_SOURCE_HOST_POLICY, resolver=lambda _: ("127.0.0.1",))


def test_disallowed_redirect_is_not_requested() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(302, headers={"location": "https://example.com/private"}, request=request)

    fetcher = Fetcher(
        FetchConfig(retries=0),
        transport=httpx.MockTransport(handler),
        resolver=_public_resolver,
    )
    try:
        resource = fetcher.fetch_http("https://bmstu.ru/start")
    finally:
        fetcher.close()

    assert resource.error_code == "redirect_host_not_allowed"
    assert resource.body == b""
    assert requested == ["https://bmstu.ru/start"]


def test_allowed_redirect_is_recorded_in_final_url_provenance() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(302, headers={"location": "https://www.bmstu.ru/final"}, request=request)
        return httpx.Response(200, content=b"official", request=request)

    fetcher = Fetcher(
        FetchConfig(retries=0),
        transport=httpx.MockTransport(handler),
        resolver=_public_resolver,
    )
    try:
        resource = fetcher.fetch_http("https://bmstu.ru/start")
    finally:
        fetcher.close()

    assert resource.ok is True
    assert resource.final_url == "https://www.bmstu.ru/final"
    assert resource.redirects == ("https://www.bmstu.ru/final",)


def test_registered_path_policy_blocks_same_host_redirect_before_request() -> None:
    requested: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(str(request.url))
        return httpx.Response(
            302,
            headers={"location": "https://priem.bmstu.ru/private/document.pdf"},
            request=request,
        )

    def allow_admission_path(url: str) -> None:
        if not url.startswith("https://priem.bmstu.ru/admission/"):
            raise SourcePolicyError("path_not_allowed", "outside registered route")

    fetcher = Fetcher(
        FetchConfig(retries=0),
        transport=httpx.MockTransport(handler),
        resolver=_public_resolver,
    )
    try:
        resource = fetcher.fetch_http(
            "https://priem.bmstu.ru/admission/rules",
            url_validator=allow_admission_path,
        )
    finally:
        fetcher.close()

    assert resource.error_code == "redirect_path_not_allowed"
    assert requested == ["https://priem.bmstu.ru/admission/rules"]


def test_official_bmstu_mirror_redirect_is_allowed() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(301, headers={"location": "https://mirror.bmstu.ru/sveden/common"}, request=request)
        return httpx.Response(200, content=b"official mirror", request=request)

    fetcher = Fetcher(
        FetchConfig(retries=0),
        transport=httpx.MockTransport(handler),
        resolver=_public_resolver,
    )
    try:
        resource = fetcher.fetch_http("https://bmstu.ru/sveden/common")
    finally:
        fetcher.close()

    assert resource.ok is True
    assert resource.final_url == "https://mirror.bmstu.ru/sveden/common"
    assert resource.redirects == ("https://mirror.bmstu.ru/sveden/common",)


def test_official_bmstu_api_mirror_redirect_is_allowed() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(
                301,
                headers={"location": "https://api.mirror.bmstu.ru/majors/baccalaureate-and-specialty"},
                request=request,
            )
        return httpx.Response(200, content=b"official API mirror", request=request)

    fetcher = Fetcher(
        FetchConfig(retries=0),
        transport=httpx.MockTransport(handler),
        resolver=_public_resolver,
    )
    try:
        resource = fetcher.fetch_http("https://api.www.bmstu.ru/majors/baccalaureate-and-specialty")
    finally:
        fetcher.close()

    assert resource.ok is True
    assert resource.final_url == "https://api.mirror.bmstu.ru/majors/baccalaureate-and-specialty"
    assert resource.redirects == ("https://api.mirror.bmstu.ru/majors/baccalaureate-and-specialty",)


def test_response_larger_than_policy_is_truncated_and_not_successful() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 2048, request=request)

    fetcher = Fetcher(
        FetchConfig(retries=0, max_body_bytes=1024),
        transport=httpx.MockTransport(handler),
        resolver=_public_resolver,
    )
    try:
        resource = fetcher.fetch_http("https://bmstu.ru/large")
    finally:
        fetcher.close()

    assert resource.error_code == "response_body_truncated"
    assert resource.truncated is True
    assert len(resource.body) == 1024
    assert resource.ok is False
