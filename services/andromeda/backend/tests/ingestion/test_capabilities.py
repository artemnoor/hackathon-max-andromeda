from __future__ import annotations

import pytest

from andromeda.ingestion.capabilities import discover_capabilities
from andromeda.ingestion.pdf_policy import DEFAULT_PDF_POLICY, PdfResourceError, PdfResourcePolicy, validate_pdf_payload, validate_page_count


def test_supported_profiles_report_required_parser_capabilities() -> None:
    statuses = discover_capabilities()

    required = {
        item.name
        for item in statuses
        if "bmstu" in item.required_profiles or "hse" in item.required_profiles
    }
    assert {"beautifulsoup4", "PyMuPDF", "pypdf", "pdfplumber", "Poppler pdftotext"} <= required
    assert all(item.available for item in statuses if item.required_profiles)


def test_capability_discovery_keeps_optional_browser_non_blocking() -> None:
    statuses = discover_capabilities(module_finder=lambda name: None, executable_finder=lambda name: None)

    browser = next(item for item in statuses if item.name == "Playwright browser fallback")
    assert browser.required_profiles == ()
    assert not browser.available
    assert all(not item.available for item in statuses if item.required_profiles)


def test_pdf_policy_rejects_invalid_and_oversized_payloads() -> None:
    with pytest.raises(PdfResourceError, match="pdf_signature_invalid"):
        validate_pdf_payload(b"not-a-pdf")
    small_policy = PdfResourcePolicy(max_bytes=1_000_000)
    with pytest.raises(PdfResourceError, match="pdf_size_limit_exceeded"):
        validate_pdf_payload(b"%PDF" + b"x" * small_policy.max_bytes, small_policy)
    with pytest.raises(PdfResourceError, match="pdf_page_limit_exceeded"):
        validate_page_count(DEFAULT_PDF_POLICY.max_pages + 1)
