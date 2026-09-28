from __future__ import annotations

from decimal import Decimal

from andromeda.modules.analytics.contracts.metrics import MetricEntityType
from andromeda.modules.analytics.contracts.public import (
    ProjectionDataQuality,
    ProjectionDataQualityStatus,
)
from andromeda.modules.analytics.contracts.query import QuerySpec
from andromeda.modules.analytics.contracts.results import (
    AnalyticsResult,
    AnalyticsResultStatus,
    AnalyticsRow,
)
from andromeda.modules.presentation.adapters.html_pdf import HtmlPdfReportRenderer
from andromeda.modules.presentation.contracts.envelope import (
    ResponseAction,
    ResponseActionItem,
    ResponseEnvelope,
)
from andromeda.modules.presentation.contracts.knowledge_response import ResponseMode
from andromeda.modules.presentation.contracts.policy import (
    ResponseFormat,
    ResponsePolicyResult,
)
from andromeda.modules.presentation.contracts.report import ReportFormat, ReportSpec
from andromeda.modules.presentation.services.envelope_builder import (
    build_response_envelope,
)


def _result() -> AnalyticsResult:
    query = QuerySpec(entity=MetricEntityType.PROGRAM, metrics=("math_share",))
    quality = ProjectionDataQuality(status=ProjectionDataQualityStatus.INSUFFICIENT_DATA, coverage=Decimal(0), confidence=Decimal(0))
    row = AnalyticsRow(entity_id="program:bmstu:09.03.01-02", metrics={}, quality=quality)
    return AnalyticsResult(query=query, rows=(row,), status=AnalyticsResultStatus.PARTIAL, coverage=Decimal(0), confidence=Decimal(0))


def test_envelope_is_channel_neutral_and_actions_are_allow_listed() -> None:
    result = _result()
    envelope = build_response_envelope(
        result,
        ResponsePolicyResult(response_format=ResponseFormat.TEXT, template="analytics-summary", reason="test"),
        text="Готово",
        actions=(ResponseActionItem(action=ResponseAction.SHOW_DETAILS, label="Подробнее", payload={"programId": "program:bmstu:09.03.01-02"}),),
        metadata={"resolution_evidence": {"program:0": "strategy=deterministic"}},
    )
    assert envelope.response_type is ResponseFormat.TEXT
    assert envelope.actions[0].action is ResponseAction.SHOW_DETAILS
    assert envelope.data["rows"]
    assert envelope.metadata["resolution_evidence"] == {"program:0": "strategy=deterministic"}
    assert "sql" not in envelope.model_dump_json().lower()


def test_legacy_envelope_defaults_to_deterministic_without_knowledge_section() -> None:
    envelope = ResponseEnvelope(
        response_type=ResponseFormat.TEXT,
        template="legacy-template",
    )

    assert envelope.response_mode is ResponseMode.DETERMINISTIC
    assert envelope.knowledge is None
    payload = envelope.model_dump(mode="json")
    assert payload["response_type"] == "text"
    assert payload["template"] == "legacy-template"
    assert payload["knowledge"] is None


def test_html_report_renderer_consumes_result_snapshot_without_requery() -> None:
    result = _result()
    spec = ReportSpec(title="Сравнение", result=result, output_format=ReportFormat.HTML)
    rendered = HtmlPdfReportRenderer().render(spec)
    assert rendered.output_format is ReportFormat.HTML
    assert rendered.media_type == "text/html"
    assert b"program:bmstu" in rendered.content
    assert spec.result is result
