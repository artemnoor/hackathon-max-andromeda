from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

from andromeda.ingestion.universities.bmstu.browser import fetch_with_browser
from andromeda.ingestion.universities.bmstu.fetch import BMSTU_SOURCE_HOST_POLICY


class _FakeRequest:
    def __init__(self, url: str, resource_type: str) -> None:
        self.url = url
        self.resource_type = resource_type


class _FakeRoute:
    def __init__(self, request: _FakeRequest) -> None:
        self.request = request
        self.aborted = False
        self.abort_code: str | None = None

    def abort(self, code: str) -> None:
        self.aborted = True
        self.abort_code = code

    def continue_(self) -> None:
        raise AssertionError("disallowed subresource must be aborted")


class _FakeResponse:
    url = "https://bmstu.ru/sveden/common/"
    status = 200
    headers = {"content-type": "text/html; charset=utf-8"}

    def body(self) -> bytes:
        return b"official page"


class _FakePage:
    url = "https://bmstu.ru/sveden/common/"

    def __init__(self) -> None:
        self._response_handler: Any = None
        self._route_handler: Any = None
        self.blocked_route: _FakeRoute | None = None

    def route(self, _pattern: str, handler: Any) -> None:
        self._route_handler = handler

    def on(self, event: str, handler: Any) -> None:
        if event == "response":
            self._response_handler = handler

    def goto(self, *_args: Any, **_kwargs: Any) -> _FakeResponse:
        self.blocked_route = _FakeRoute(_FakeRequest("https://metrics.eu.bmstu.ru/matomo.js", "script"))
        self._route_handler(self.blocked_route)
        assert self.blocked_route.aborted is True
        assert self.blocked_route.abort_code == "blockedbyclient"
        response = _FakeResponse()
        self._response_handler(response)
        return response

    def wait_for_load_state(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def evaluate(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def content(self) -> str:
        return "<html><body>official page</body></html>"


class _FakeBrowser:
    def __init__(self) -> None:
        self.page = _FakePage()

    def new_page(self, **_kwargs: Any) -> _FakePage:
        return self.page

    def close(self) -> None:
        return None


class _FakeChromium:
    def launch(self, **_kwargs: Any) -> _FakeBrowser:
        return _FakeBrowser()


class _FakePlaywright:
    def __init__(self) -> None:
        self.chromium = _FakeChromium()


class _FakePlaywrightContext:
    def __enter__(self) -> _FakePlaywright:
        return _FakePlaywright()

    def __exit__(self, *_args: Any) -> None:
        return None


def test_browser_blocks_external_subresources_without_rejecting_official_document(monkeypatch: Any) -> None:
    playwright_package = ModuleType("playwright")
    playwright_api = ModuleType("playwright.sync_api")
    playwright_api.sync_playwright = _FakePlaywrightContext
    monkeypatch.setitem(sys.modules, "playwright", playwright_package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", playwright_api)

    resource = fetch_with_browser(
        "https://bmstu.ru/sveden/common/",
        policy=BMSTU_SOURCE_HOST_POLICY,
        resolver=lambda _host: ("8.8.8.8",),
    )

    assert resource.ok is True
    assert resource.error is None
