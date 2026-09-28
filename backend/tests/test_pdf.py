from andromeda.ingestion.universities.bmstu.pdf import extract_admission_year, iter_order_rows, iter_registered_rows


def test_parses_enrollment_text_rows() -> None:
    text = (
        "X1. Код ЕПГУ: 1070386; Рег.№: A2251; Сумма баллов: "
        "247 (ВИ 247, ИД 0); X2. Код ЕПГУ: 1184848; "
        "Сумма баллов: 259 (ВИ 249, ИД 10);"
    )
    rows = list(iter_order_rows(text))
    assert [row["applicant_id"] for row in rows] == ["1070386", "1184848"]
    assert [row["score"] for row in rows] == [247, 259]
    assert rows[1]["score_individual"] == 10


def test_parses_registered_rows_with_wrapped_columns() -> None:
    text = """1
831080
A0622
09.03.03 (ОФ),
09.03.04 (ОФ)
2 831395 * A1657 15.03.06 (ОФ)
"""
    rows = list(iter_registered_rows(text))
    assert [row["applicant_id"] for row in rows] == ["831080", "831395"]
    assert rows[0]["row_no"] == 1
    assert rows[1]["is_special"] is True


def test_extracts_year_from_document_header() -> None:
    assert extract_admission_year("Список поступающих на 1-й курс по состоянию на 07.09.2026") == 2026
