from andromeda.ingestion.universities.bmstu.html import extract_links, extract_tables, parse_number, parse_page


def test_extracts_table_links_and_numbers() -> None:
    html = """
    <html><body>
      <h2>2026/2027 учебный год</h2>
      <table><thead><tr><th>Код</th><th>Наименование</th><th>Цена, руб.</th></tr></thead>
      <tbody><tr><td>09.03.04</td><td>Программная инженерия</td><td>699 000</td></tr></tbody></table>
      <a href="/docs/rules.pdf">Правила приёма</a>
    </body></html>
    """
    page = parse_page(html, "https://example.test/cost")
    assert page.tables[0]["context"] == "2026/2027 учебный год"
    assert page.tables[0]["rows"][0]["Код"] == "09.03.04"
    assert parse_number(page.tables[0]["rows"][0]["Цена, руб."]) == 699000
    assert extract_links(page.soup, "https://example.test/cost")[0]["url"] == "https://example.test/docs/rules.pdf"
