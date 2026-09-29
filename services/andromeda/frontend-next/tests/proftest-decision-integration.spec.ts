import { expect, test, type Page } from "@playwright/test";

test.describe.configure({ mode: "serial" });

test("guest proftest hands off to the shared decision context", async ({ page }) => {
  test.setTimeout(120_000);
  await completeProftest(page);

  const handoff = page.getByTestId("proftest-decision-handoff");
  await expect(handoff).toBeVisible();
  await expect(handoff).toContainText("Профиль уточнён");
  await expect(handoff).toContainText("Сохранённые варианты не изменены автоматически");
  await expect(page.getByTestId("proftest-evidence")).toContainText("Набор вопросов: proftest-v3");
  await expect(page.getByTestId("proftest-recommendation-evidence").first()).toBeVisible();

  await handoff.getByRole("button", { name: "Открыть «Мой выбор»" }).click();
  await expect(page.getByTestId("decision-page")).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("decision-page")).toBeVisible();
});

test("proftest completion never changes an existing shortlist", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/?view=catalog");
  await expect(page.getByTestId("catalog-page")).toBeVisible();
  const addButtons = page.getByRole("button", { name: "Добавить в shortlist" });
  const availablePrograms = await addButtons.count();
  expect(availablePrograms).toBeGreaterThanOrEqual(2);
  await addButtons.nth(0).click();
  await expect(page.getByRole("button", { name: "Убрать из shortlist" })).toHaveCount(1);
  await expect.poll(() => addButtons.count(), { timeout: 30_000 }).toBe(availablePrograms - 1);
  await page.getByRole("button", { name: "Добавить в shortlist" }).first().click();
  await expect(page.getByRole("button", { name: "Убрать из shortlist" })).toHaveCount(2);

  await completeProftest(page);
  await page.getByTestId("proftest-decision-handoff").getByRole("button", { name: "Открыть «Мой выбор»" }).click();
  await expect(page.getByTestId("decision-page")).toBeVisible();
  await expect(page.getByTestId("decision-page").getByRole("button", { name: "Убрать из shortlist" })).toHaveCount(2);
});

test("recommendations remain an independent entry point without a profile", async ({ page }) => {
  await page.goto("/?view=recommendations");
  await expect(page.getByTestId("recommendations-page")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Предложения системы").first()).toBeVisible();
  await expect(page.getByText("Сначала можно уточнить предпочтения")).toHaveCount(0);
});

async function completeProftest(page: Page): Promise<void> {
  await page.goto("/?view=proftest");
  const intro = page.getByTestId("proftest-intro");
  const results = page.getByTestId("proftest-results");
  await expect(intro).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("proftest-start")).toBeEnabled();
  await page.getByTestId("proftest-start").click();
  await expect(page.getByTestId("proftest-question")).toBeVisible({ timeout: 30_000 });

  for (let step = 0; step < 9; step += 1) {
    if (await results.isVisible().catch(() => false)) return;
    const options = page.getByTestId("proftest-option");
    if (await options.count()) {
      await options.first().click();
    } else if (await page.getByRole("button", { name: "Пропустить" }).isVisible().catch(() => false)) {
      await page.getByRole("button", { name: "Пропустить" }).click();
    } else {
      await page.getByRole("button", { name: "Не уверен" }).click();
    }
    const next = page.getByTestId("proftest-next");
    await expect(next).toBeEnabled();
    const previousQuestionId = await page.getByTestId("proftest-question").getAttribute("data-question-id");
    const nextResponse = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/proftest/sessions/current/next"),
      { timeout: 30_000 },
    );
    await next.click();
    const response = await nextResponse;
    await expect(response.ok()).toBe(true);
    const payload = await response.json() as { currentQuestion?: unknown };
    if (payload.currentQuestion == null) {
      await expect(results).toBeVisible({ timeout: 60_000 });
      return;
    }
    await expect.poll(async () => {
      if (await results.isVisible().catch(() => false)) return "results";
      const questionId = await page.getByTestId("proftest-question").getAttribute("data-question-id").catch(() => null);
      return questionId && questionId !== previousQuestionId ? questionId : "pending";
    }, { timeout: 15_000, intervals: [100, 250, 500, 1_000] }).not.toBe("pending");
  }

  if (!await results.isVisible().catch(() => false)) {
    const complete = page.getByTestId("proftest-complete");
    if (await complete.isVisible().catch(() => false)) await complete.click();
  }
  await expect(results).toBeVisible({ timeout: 30_000 });
}
