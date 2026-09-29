from __future__ import annotations

import httpx

from andromeda.ingestion.universities.bmstu.fetch import FetchConfig, Fetcher


def test_retry_policy_handles_5xx_with_bounded_exponential_delay() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        status = 500 if calls < 3 else 200
        return httpx.Response(status, content=b"ok", request=request)

    fetcher = Fetcher(
        FetchConfig(retries=2, retry_delay_seconds=0.2, retry_max_delay_seconds=0.8),
        transport=httpx.MockTransport(handler),
        resolver=lambda _: ("8.8.8.8",),
        sleep_fn=sleeps.append,
    )
    try:
        resource = fetcher.fetch_http("https://bmstu.ru/retry")
    finally:
        fetcher.close()

    assert resource.ok is True
    assert resource.attempts == 3
    assert sleeps == [0.2, 0.4]


def test_retry_after_is_capped_and_exhaustion_is_diagnostic() -> None:
    calls = 0
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429, headers={"retry-after": "60"}, content=b"busy", request=request)

    fetcher = Fetcher(
        FetchConfig(retries=1, retry_delay_seconds=0.2, retry_after_max_seconds=1.5),
        transport=httpx.MockTransport(handler),
        resolver=lambda _: ("8.8.8.8",),
        sleep_fn=sleeps.append,
    )
    try:
        resource = fetcher.fetch_http("https://bmstu.ru/rate-limited")
    finally:
        fetcher.close()

    assert calls == 2
    assert sleeps == [1.5]
    assert resource.error_code == "retry_exhausted"
    assert resource.retry_class == "http_429"
    assert resource.attempts == 2
