from __future__ import annotations

import pytest

from andromeda.ingestion.fetch_policy import (
    SourcePolicyError,
    resolve_redirect,
    validate_source_url,
)
from andromeda.ingestion.universities.bmstu.fetch import BMSTU_SOURCE_HOST_POLICY
from andromeda.ingestion.universities.hse.fetch import HSE_SOURCE_HOST_POLICY
from andromeda.ingestion.universities.hse.html import official_hse_url


def test_bmstu_allows_explicit_public_document_hosts_only() -> None:
    resolver = lambda _: ("8.8.8.8",)
    validate_source_url("https://api.www.bmstu.ru/majors/", BMSTU_SOURCE_HOST_POLICY, resolver=resolver)
    validate_source_url("https://mirror.bmstu.ru/sveden/common", BMSTU_SOURCE_HOST_POLICY, resolver=resolver)
    validate_source_url("https://api.mirror.bmstu.ru/majors/", BMSTU_SOURCE_HOST_POLICY, resolver=resolver)
    validate_source_url("https://olymp.bmstu.ru/ru/engeneering-olymp", BMSTU_SOURCE_HOST_POLICY, resolver=resolver)
    validate_source_url("https://storage.yandex.net/plan.pdf", BMSTU_SOURCE_HOST_POLICY, resolver=resolver)
    with pytest.raises(SourcePolicyError, match="not in the adapter allowlist"):
        validate_source_url("https://example.com/plan.pdf", BMSTU_SOURCE_HOST_POLICY, resolver=resolver)


def test_hse_subdomains_are_allowed_but_non_hse_hosts_are_not() -> None:
    resolver = lambda _: ("8.8.8.8",)
    validate_source_url("https://admissions.hse.ru/programmes", HSE_SOURCE_HOST_POLICY, resolver=resolver)
    assert official_hse_url("https://spb.hse.ru/ba/finlist")
    with pytest.raises(SourcePolicyError):
        validate_source_url("https://hse.example.com/programmes", HSE_SOURCE_HOST_POLICY, resolver=resolver)


def test_redirect_validation_checks_final_host_and_ip() -> None:
    resolver = lambda host: ("8.8.8.8",) if host == "bmstu.ru" else ("10.0.0.1",)
    with pytest.raises(SourcePolicyError, match="non-public"):
        resolve_redirect("https://bmstu.ru/start", "https://www.bmstu.ru/private", BMSTU_SOURCE_HOST_POLICY, resolver=resolver)
