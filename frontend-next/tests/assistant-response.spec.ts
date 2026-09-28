import { expect, test } from "@playwright/test";

test("assistant renders admission data gaps instead of implying a positive result", async ({ page }) => {
  await page.route("**/assistant/query", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        state: "complete",
        session_id: "query-session:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        revision: 2,
        question: null,
        options: [],
        missing_slots: [],
        response: {
          response_type: "text",
          template: "admission-fit-summary",
          text: "Проверено программ: 1",
          data: {
            outcomes: {
              by_program_id: {
                "program:bmstu:09.03.01-02": {
                  program_id: "program:bmstu:09.03.01-02",
                  status: "insufficient_data",
                  result: null,
                  data_gaps: [{ kind: "data_gap", message: "Для выбранных условий опубликовано несколько наборов." }],
                },
              },
            },
          },
          actions: [],
          result_reference: "query-session:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
          evidence_available: false,
          has_source_gaps: true,
        },
        query: null,
        admission_request: null,
        admission_requests: [],
        admission_result: null,
      }),
    });
  });

  await page.goto("/?view=assistant");
  await page.getByRole("textbox", { name: "Вопрос к Andromeda" }).fill("Куда я прохожу с 270?");
  await page.getByRole("button", { name: "Отправить вопрос" }).click();

  await expect(page.getByText(/09\.03\.01-02 — недостаточно данных/)).toBeVisible();
  await expect(page.getByText(/это не подтверждение поступления/)).toBeVisible();
});

test("assistant shows funding clarification options and discloses admission defaults", async ({ page }) => {
  let requestCount = 0;
  await page.route("**/assistant/query", async (route) => {
    requestCount += 1;
    if (requestCount === 1) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          state: "needs_clarification",
          session_id: "query-session:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
          revision: 2,
          question: "Рассматривать бюджет или платное обучение?",
          options: ["Бюджет", "Платное"],
          missing_slots: ["funding"],
          response: null,
          query: null,
          admission_request: null,
          admission_requests: [],
          admission_result: null,
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        state: "complete",
        session_id: "query-session:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        revision: 3,
        question: null,
        options: [],
        missing_slots: [],
        response: {
          response_type: "text",
          template: "admission-fit-summary",
          text: "Проверено программ: 2. Параметры: год приёма — 2026 (последний опубликованный год); форма — очная (по умолчанию); финансирование — бюджет.",
          data: { outcomes: { by_program_id: {} } },
          metadata: { assumptions: ["Год приёма: 2026", "Очная форма по умолчанию"] },
          actions: [],
        },
        query: null,
        admission_request: null,
        admission_requests: [],
        admission_result: null,
      }),
    });
  });

  await page.goto("/?view=assistant");
  await page.getByRole("textbox", { name: "Вопрос к Andromeda" }).fill("Куда я прохожу с 270?");
  await page.getByRole("button", { name: "Отправить вопрос" }).click();
  await expect(page.getByText("Рассматривать бюджет или платное обучение?")).toBeVisible();
  const dialogue = page.locator('[aria-live="polite"]');
  await expect(dialogue).toContainText("• Бюджет");
  await expect(dialogue).toContainText("• Платное");

  await page.getByRole("textbox", { name: "Вопрос к Andromeda" }).fill("бюджет");
  await page.getByRole("button", { name: "Отправить вопрос" }).click();
  await expect(page.getByText(/2026 \(последний опубликованный год\)/)).toBeVisible();
  await expect(page.getByText(/очная \(по умолчанию\)/)).toBeVisible();
});
