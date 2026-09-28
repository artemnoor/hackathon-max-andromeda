from __future__ import annotations

from datetime import UTC, datetime

from pydantic import HttpUrl

from andromeda.ingestion.contracts.raw import RawAdmissionBenefitDocument, SourceLocator
from andromeda.ingestion.universities.bmstu.parser.admission_benefit_html import (
    parse_benefit_html,
)
from andromeda.ingestion.universities.bmstu.parser.admission_benefit_tables import (
    parse_benefit_tables,
)
from andromeda.ingestion.universities.bmstu.parser.special_olympiads import (
    parse_special_olympiad_tables,
)


def _document(kind: str) -> RawAdmissionBenefitDocument:
    url = "https://api.www.bmstu.ru/file/124777/download" if kind == "appendix_5_1" else "https://api.www.bmstu.ru/file/122150/download"
    return RawAdmissionBenefitDocument(
        document_kind=kind,
        document_title=f"Приложение {kind.removeprefix('appendix_')} 2026",
        admission_year=2026,
        source_url=HttpUrl(url),
        source_snapshot_hash="a" * 64,
        source_run_id="ingest:" + "b" * 32,
        captured_at=datetime(2026, 9, 22, tzinfo=UTC),
        locator=SourceLocator(source_url=HttpUrl(url)),
        parser_version="bmstu-admission-parser.v1",
    )


def test_appendix_51_preserves_winner_and_prize_cells_and_all_except_scope() -> None:
    document = _document("appendix_5_1")
    records, diagnostics = parse_benefit_tables(
        document,
        (
            {
                "page": 4,
                "table": 1,
                "rows": [
                    ["№", "Полное наименование олимпиады", "Профиль олимпиады", "Победитель", "Призер", "Направления"],
                    ["55", "Олимпиада школьников «Шаг в будущее»", "инженерное дело", "Предоставляется", "Предоставляется", "Все, кроме 01.03.02, 09.03.04, 10.05.01, 10.05.03"],
                ],
            },
        ),
    )

    assert diagnostics == ()
    assert len(records) == 2
    assert {candidate.value for record in records for candidate in record.normalized_candidates if candidate.field == "result_type"} == {"winner", "prize_winner"}
    assert all(record.source_snapshot_hash == "a" * 64 for record in records)
    assert all(any(candidate.value == "all_except" for candidate in record.normalized_candidates if candidate.field == "scope_mode") for record in records)
    codes = {candidate.value for record in records for candidate in record.normalized_candidates if candidate.field == "scope_direction_code"}
    assert codes == {"01.03.02", "09.03.04", "10.05.01", "10.05.03"}
    assert all(any(candidate.field == "benefit_type" and candidate.value == "bvi" for candidate in record.normalized_candidates) for record in records)


def test_scope_context_row_is_carried_to_pdf_continuation_table() -> None:
    records, diagnostics = parse_benefit_tables(
        _document("appendix_5_1"),
        (
            {
                "page": 1,
                "table": 1,
                "rows": [
                    ["№", "Олимпиада", "Профиль", "Результат"],
                    ["Для направлений: 01.03.02, 09.03.04", "", "", ""],
                ],
            },
            {
                "page": 2,
                "table": 1,
                "rows": [
                    ["55", "Олимпиада X", "профиль", "Предоставляется", "Предоставляется"],
                    ["56", "Олимпиада Y", "профиль", "Предоставляется", "Предоставляется"],
                ],
            },
        ),
    )

    assert diagnostics == ()
    assert records
    assert all(
        {candidate.value for candidate in record.normalized_candidates if candidate.field == "scope_direction_code"}
        == {"01.03.02", "09.03.04"}
        for record in records
    )


def test_appendix_53_same_olympiad_shape_is_a_separate_100_point_kind() -> None:
    records, _ = parse_benefit_tables(
        _document("appendix_5_3"),
        (
            {
                "page": 2,
                "table": 1,
                "rows": [
                    ["№", "Олимпиада", "Профиль", "Победитель", "Призер"],
                    ["55", "Олимпиада школьников «Шаг в будущее»", "физика", "Предоставляется", "Не предоставляется"],
                ],
            },
        ),
    )

    assert len(records) == 2
    assert all(any(candidate.field == "benefit_type" and candidate.value == "one_hundred_points" for candidate in record.normalized_candidates) for record in records)
    assert {candidate.value for record in records for candidate in record.normalized_candidates if candidate.field == "benefit_granted"} == {"yes", "no"}


def test_continuation_table_without_repeated_header_uses_official_status_columns() -> None:
    records, diagnostics = parse_benefit_tables(
        _document("appendix_5_1"),
        (
            {
                "page": 2,
                "table": 1,
                "rows": [
                    [
                        "55",
                        "Олимпиада X",
                        "профиль",
                        "направление",
                        "II",
                        "физика",
                        "Предоставляется",
                        "Не предоставляется",
                    ],
                    [
                        "56",
                        "Олимпиада Y",
                        "профиль",
                        "направление",
                        "II",
                        "математика",
                        "Предоставляется",
                        "Не предоставляется",
                    ],
                ],
            },
        ),
    )

    assert diagnostics == ()
    assert {candidate.value for record in records for candidate in record.normalized_candidates if candidate.field == "result_type"} == {
        "winner",
        "prize_winner",
    }
    assert {candidate.value for record in records for candidate in record.normalized_candidates if candidate.field == "benefit_granted"} == {
        "yes",
        "no",
    }


def test_appendix_52_combined_official_heading_preserves_both_branch_campuses() -> None:
    records, diagnostics = parse_benefit_tables(
        _document("appendix_5_2"),
        (
            {
                "page": 1,
                "table": 1,
                "rows": [
                    ["№", "Олимпиада", "Профиль", "Предмет", "Уровень", "Подтверждение", "Для победителей и призеров"],
                    ["1", "Олимпиада X", "математика", "математика", "II", "математика", "все НП(С) КФ и МФ"],
                ],
            },
        ),
    )

    assert diagnostics == ()
    assert len(records) == 2
    assert all(any(candidate.field == "benefit_type" and candidate.value == "bvi" for candidate in record.normalized_candidates) for record in records)
    assert all(any(candidate.field == "benefit_granted" and candidate.value == "yes" for candidate in record.normalized_candidates) for record in records)
    assert all(any(candidate.field == "scope_mode" and candidate.value == "only" for candidate in record.normalized_candidates) for record in records)
    assert {
        candidate.value
        for record in records
        for candidate in record.normalized_candidates
        if candidate.field == "scope_campus_id"
    } == {"campus:bmstu-kaluga", "campus:bmstu-mytishchi"}


def test_confirmation_threshold_is_extracted_from_the_official_header_not_defaulted() -> None:
    records, _ = parse_benefit_tables(
        _document("appendix_5_3"),
        (
            {
                "page": 1,
                "table": 1,
                "rows": [
                    ["№", "Олимпиада", "Профиль", "Подтверждение олимпиады 75 баллами по ЕГЭ", "Победитель"],
                    ["1", "Олимпиада X", "математика", "математика", "Предоставляется"],
                ],
            },
        ),
    )

    assert any(candidate.field == "confirmation_min_score" and candidate.value == "75" for candidate in records[0].normalized_candidates)


def test_ambiguous_result_is_review_diagnostic_and_not_dropped() -> None:
    records, diagnostics = parse_benefit_tables(
        _document("appendix_5_3"),
        (
            {
                "page": 3,
                "table": 1,
                "rows": [["Олимпиада", "Профиль"], ["Неизвестная олимпиада", "Неизвестный профиль"]],
            },
        ),
    )

    assert len(records) == 1
    assert records[0].record_kind.value == "benefit_rule"
    assert diagnostics[0].code == "ambiguous_table_row"


def test_official_html_profile_table_keeps_heading_locator() -> None:
    document = _document("official_olympiad_page")
    records, diagnostics = parse_benefit_html(
        document,
        """
        <html><body><h1>Профили олимпиады</h1><table>
        <tr><th>Олимпиада</th><th>Профиль</th><th>Направления</th></tr>
        <tr><td>Шаг в будущее</td><td>Программирование</td><td>09.03.03</td></tr>
        </table></body></html>
        """.encode(),
    )

    assert diagnostics == ()
    assert records
    assert records[0].locator.page == 1
    assert any(candidate.field == "scope_direction_code" and candidate.value == "09.03.03" for candidate in records[0].normalized_candidates)


def test_empty_merged_header_gets_a_structural_name() -> None:
    records, diagnostics = parse_benefit_tables(
        _document("appendix_5_3"),
        (
            {
                "page": 1,
                "table": 1,
                "rows": [
                    ["№", "Олимпиада", "", "Победитель"],
                    ["1", "Олимпиада X", "математика", "Предоставляется"],
                ],
            },
        ),
    )

    assert records
    assert diagnostics == ()
    assert all(cell.header for cell in records[0].cells)
    assert any(cell.header == "column_3" for cell in records[0].cells)


def test_oversized_pdf_header_is_bounded_only_in_cell_projection() -> None:
    long_header = "Направления и условия " + ("для поступления, " * 50)
    records, diagnostics = parse_benefit_tables(
        _document("appendix_5_3"),
        (
            {
                "page": 1,
                "table": 1,
                "rows": [
                    ["№", "Олимпиада", long_header, "Победитель"],
                    ["1", "Олимпиада X", "математика", "Предоставляется"],
                ],
            },
        ),
    )

    assert diagnostics == ()
    assert records
    assert max(len(cell.header) for cell in records[0].cells) <= 512
    assert records[0].cells[2].header == f"{long_header[:509]}..."


def test_appendix_54_special_parser_builds_vosh_bvi_and_hundred_point_candidates() -> None:
    records, diagnostics = parse_special_olympiad_tables(
        _document("appendix_5_4"),
        (
            {
                "page": 1,
                "table": 1,
                "rows": [
                    ["Профиль ВОШ", "Общеобразовательное вступительное испытание"],
                    ["Математика", "Математика"],
                ],
            },
            {
                "page": 2,
                "table": 3,
                "rows": [
                    ["Профиль ВОШ", "НПС для предоставления права на прием без вступительных испытаний"],
                    ["Математика", "01.03.02 и 02.03.01"],
                ],
            },
        ),
    )

    assert diagnostics == ()
    assert len(records) == 4
    assert {candidate.value for record in records for candidate in record.normalized_candidates if candidate.field == "route"} == {"vosh"}
    assert {candidate.value for record in records for candidate in record.normalized_candidates if candidate.field == "result_type"} == {"winner", "prize_winner"}
    assert {candidate.value for record in records for candidate in record.normalized_candidates if candidate.field == "benefit_type"} == {"bvi", "one_hundred_points"}


def test_appendix_55_special_parser_uses_team_member_for_international_olympiads() -> None:
    records, diagnostics = parse_special_olympiad_tables(
        _document("appendix_5_5"),
        (
            {
                "page": 1,
                "table": 1,
                "rows": [
                    ["Профиль Международной олимпиады", "", "Общеобразовательное вступительное испытание"],
                    ["", "Международная математическая олимпиада", "Математика"],
                ],
            },
            {
                "page": 1,
                "table": 3,
                "rows": [
                    ["Профиль Международной олимпиады", "НПС для предоставления права на прием без вступительных испытаний"],
                    ["Международная математическая олимпиада", "Любое НПС"],
                ],
            },
        ),
    )

    assert diagnostics == ()
    assert len(records) == 2
    assert all(any(candidate.value == "team_member" for candidate in record.normalized_candidates if candidate.field == "result_type") for record in records)
    assert any(any(candidate.value == "all" for candidate in record.normalized_candidates if candidate.field == "scope_mode") for record in records)
