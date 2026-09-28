from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[2]
LIST_URL = "https://bmstu.ru/bachelor/majors"
OUTPUT = ROOT / "admission-exams.js"


def main() -> None:
    profile_paths = sorted((ROOT / "output").glob("*/profile.json"), key=lambda path: path.stat().st_mtime)
    target_codes: set[str] = set()
    if profile_paths:
        profile = json.loads(profile_paths[-1].read_text(encoding="utf-8"))
        target_codes = {str(item["code"]) for item in profile.get("directions", []) if item.get("code")}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(locale="ru-RU")
        page.goto(LIST_URL, wait_until="networkidle", timeout=120_000)
        previous_count = 0
        for _ in range(20):
            hrefs = page.eval_on_selector_all(
                'a[href^="/bachelor/majors/"]',
                "links => [...new Set(links.map(link => link.getAttribute('href')).filter(Boolean))]",
            )
            if len(hrefs) == previous_count:
                break
            previous_count = len(hrefs)
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(2_000)

        hrefs = page.eval_on_selector_all(
            'a[href^="/bachelor/majors/"]',
            "links => [...new Set(links.map(link => link.getAttribute('href')).filter(Boolean))]",
        )

        catalog: dict[str, dict] = {}
        if OUTPUT.exists():
            saved = OUTPUT.read_text(encoding="utf-8").split("=", 1)[1].strip()
            catalog = json.loads(saved[:-1]).get("directions", {})

        def add_detail(url: str, index: int, total: int) -> None:
            page.goto(url, wait_until="networkidle", timeout=120_000)
            data = page.evaluate(
                """() => {
                  const state = window.__NEXT_DATA__?.props?.initialState || {};
                  return state.bachelorMajorsDetails?.data || null;
                }"""
            )
            if not isinstance(data, dict):
                return

            additional = data.get("additional") or {}
            direction_code = additional.get("code")
            if not direction_code:
                return

            points = []
            for point in data.get("points") or []:
                if not isinstance(point, dict) or not point.get("title"):
                    continue
                points.append(
                    {
                        "subject": point.get("title"),
                        "minimum_score": point.get("point"),
                        "is_choice": bool(point.get("isChoice")),
                    }
                )

            catalog[str(direction_code)] = {
                "direction_code": str(direction_code),
                "title": additional.get("name"),
                "source_url": url,
                "source_name": "Официальная карточка направления BMSTU",
                "year": 2026,
                "exams": points,
                "allowed_combinations": [
                    {
                        "type": "choice",
                        "subjects": [point["subject"] for point in points if point["is_choice"]],
                    }
                ]
                if any(point["is_choice"] for point in points)
                else [],
                "minimum_scores": [
                    {"subject": point["subject"], "score": point["minimum_score"]}
                    for point in points
                ],
                "places": data.get("places") or [],
                "price": data.get("price") or [],
            }
            print(f"[{index}/{total}] {direction_code}: {len(points)} экзаменов")

        if not catalog:
            for index, href in enumerate(hrefs, start=1):
                add_detail(f"https://bmstu.ru{href}", index, len(hrefs))

        missing_codes = sorted(target_codes - set(catalog))
        if missing_codes:
            page.goto(LIST_URL, wait_until="networkidle", timeout=120_000)
            missing_hrefs: set[str] = set()
            for code in missing_codes:
                search = page.locator("input").first
                search.fill(code)
                search.press("Enter")
                page.wait_for_timeout(2_500)
                filtered_hrefs = page.eval_on_selector_all(
                    'a[href^="/bachelor/majors/"]',
                    "links => [...new Set(links.map(link => link.getAttribute('href')).filter(Boolean))]",
                )
                missing_hrefs.update(filtered_hrefs)
                page.goto(LIST_URL, wait_until="networkidle", timeout=120_000)
            for href in sorted(missing_hrefs):
                url = f"https://bmstu.ru{href}"
                before = len(catalog)
                add_detail(url, before + 1, len(target_codes))

        browser.close()

    payload = {
        "source": LIST_URL,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "directions": catalog,
    }
    OUTPUT.write_text(
        "window.BMSTU_ADMISSION_EXAMS = "
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + ";\n",
        encoding="utf-8",
    )
    print(f"Сохранено направлений: {len(catalog)} -> {OUTPUT}")


if __name__ == "__main__":
    main()
