from __future__ import annotations

import json
import threading

import httpx
import pytest
from andromeda.infrastructure.adapters.polza_naturalizer import PolzaNaturalizer
from andromeda.infrastructure.config.settings import Settings
from andromeda.modules.presentation.contracts.verbalization import (
    PresentationSectionKind,
    PresentationSectionRef,
    ResponseNaturalizationRequest,
    ResponseNaturalizationResult,
    ResponseNaturalizationSection,
    ResponseNaturalizedSection,
    section_reference_id,
)


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "presentation_llm_enabled": True,
        "polza_api_key": "provider-secret-test-value",
    }
    values.update(overrides)
    return Settings(**values)  # type: ignore[arg-type]


def _request() -> ResponseNaturalizationRequest:
    section_id = "section:" + "a" * 64
    reference_id = section_reference_id(section_id)
    section = PresentationSectionRef(
        section_id=section_id,
        kind=PresentationSectionKind.STATUS,
    )
    return ResponseNaturalizationRequest(
        sections=(
            ResponseNaturalizationSection(
                section=section,
                text="Статус: правило принято и опубликовано для будущего периода.",
                allowed_reference_ids=(reference_id,),
            ),
        ),
        required_section_order=(section_id,),
    )


def _provider_response(request: ResponseNaturalizationRequest) -> httpx.Response:
    sections = tuple(
        ResponseNaturalizedSection(
            section_id=section.section.section_id,
            text=section.text,
            reference_ids=(section_reference_id(section.section.section_id),),
        )
        for section in request.sections
    )
    result = ResponseNaturalizationResult(sections=sections)
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": result.model_dump_json()}}]},
    )


def test_polza_request_is_fixed_bounded_and_does_not_send_rate_identity() -> None:
    request = _request()
    observed: list[httpx.Request] = []

    def handler(provider_request: httpx.Request) -> httpx.Response:
        observed.append(provider_request)
        return _provider_response(request)

    naturalizer = PolzaNaturalizer(
        _settings(), transport_factory=lambda: httpx.MockTransport(handler)
    )
    result = naturalizer.naturalize(request, rate_limit_key="private-owner-key")

    assert len(observed) == 1
    assert str(observed[0].url) == "https://polza.ai/api/v1/chat/completions"
    assert observed[0].headers["authorization"] == "Bearer provider-secret-test-value"
    body = observed[0].content.decode("utf-8")
    assert "private-owner-key" not in body
    assert "provider-secret-test-value" not in body
    payload = json.loads(body)
    assert payload["model"] == "deepseek/deepseek-v4.1-flash"
    assert payload["temperature"] == 0
    assert payload["max_tokens"] == 1200
    assert payload["response_format"] == {"type": "json_object"}
    assert result.sections[0].section_id == request.sections[0].section.section_id


def test_polza_prompt_declares_the_naturalized_output_contract() -> None:
    request = _request()
    observed: list[httpx.Request] = []

    def handler(provider_request: httpx.Request) -> httpx.Response:
        observed.append(provider_request)
        return _provider_response(request)

    naturalizer = PolzaNaturalizer(
        _settings(), transport_factory=lambda: httpx.MockTransport(handler)
    )
    naturalizer.naturalize(request, rate_limit_key="opaque-owner")

    payload = json.loads(observed[0].content)
    system_prompt = payload["messages"][0]["content"]
    assert '"schema_version"' in system_prompt
    assert '"source-backed-naturalization.v1"' in system_prompt
    assert '"sections"' in system_prompt
    assert '"section_id"' in system_prompt
    assert '"reference_ids"' in system_prompt
    assert "Do not copy request-only fields" in system_prompt


def test_polza_does_not_follow_redirects_or_retry_provider_failures() -> None:
    request = _request()
    observed: list[httpx.Request] = []

    def handler(provider_request: httpx.Request) -> httpx.Response:
        observed.append(provider_request)
        return httpx.Response(302, headers={"Location": "https://attacker.invalid"})

    naturalizer = PolzaNaturalizer(
        _settings(), transport_factory=lambda: httpx.MockTransport(handler)
    )

    with pytest.raises(httpx.HTTPStatusError):
        naturalizer.naturalize(request, rate_limit_key="opaque-owner")

    assert len(observed) == 1
    assert str(observed[0].url) == "https://polza.ai/api/v1/chat/completions"


def test_polza_rejects_oversized_provider_response_without_buffering_unbounded_data() -> (
    None
):
    request = _request()

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=b"x" * 65_000,
            headers={"Content-Type": "application/json"},
        )

    naturalizer = PolzaNaturalizer(
        _settings(), transport_factory=lambda: httpx.MockTransport(handler)
    )

    with pytest.raises(ValueError, match="size limit"):
        naturalizer.naturalize(request, rate_limit_key="opaque-owner")


def test_polza_rate_limit_is_per_hashed_owner_and_bounded() -> None:
    request = _request()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _provider_response(request)

    naturalizer = PolzaNaturalizer(
        _settings(presentation_llm_rate_limit_max=1),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    naturalizer.naturalize(request, rate_limit_key="owner-a")
    naturalizer.naturalize(request, rate_limit_key="owner-b")

    with pytest.raises(RuntimeError, match="rate- or circuit-limited"):
        naturalizer.naturalize(request, rate_limit_key="owner-a")
    assert calls == 2
    assert "owner-a" not in repr(naturalizer._rate_events)


def test_polza_concurrency_gate_fails_fast() -> None:
    request = _request()
    entered = threading.Event()
    release = threading.Event()
    results: list[ResponseNaturalizationResult] = []

    def handler(_: httpx.Request) -> httpx.Response:
        entered.set()
        if not release.wait(timeout=2):
            raise TimeoutError("test did not release provider request")
        return _provider_response(request)

    naturalizer = PolzaNaturalizer(
        _settings(presentation_llm_max_concurrency=1),
        transport_factory=lambda: httpx.MockTransport(handler),
    )

    def first_request() -> None:
        results.append(naturalizer.naturalize(request, rate_limit_key="owner-a"))

    thread = threading.Thread(target=first_request)
    thread.start()
    try:
        assert entered.wait(timeout=1)
        with pytest.raises(RuntimeError, match="concurrency limit"):
            naturalizer.naturalize(request, rate_limit_key="owner-b")
    finally:
        release.set()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert len(results) == 1


def test_polza_opens_circuit_after_bounded_consecutive_failures(caplog) -> None:
    request = _request()
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503)

    naturalizer = PolzaNaturalizer(
        _settings(presentation_llm_rate_limit_max=10),
        transport_factory=lambda: httpx.MockTransport(handler),
    )
    for index in range(4):
        with pytest.raises(httpx.HTTPStatusError):
            naturalizer.naturalize(request, rate_limit_key=f"owner-{index}")
    with pytest.raises(RuntimeError, match="rate- or circuit-limited"):
        naturalizer.naturalize(request, rate_limit_key="another-owner")

    assert calls == 4
    assert "provider-secret-test-value" not in caplog.text
    assert "owner-0" not in caplog.text
