import { expect, test, type Page } from "@playwright/test";

test("anonymous MVP journey keeps explicit choice and renders degraded states honestly", async ({ page }) => {
  test.setTimeout(150_000);

  await page.goto("/?view=catalog");
  await expect(page.getByTestId("catalog-page")).toBeVisible({ timeout: 30_000 });
  const shortlistButtons = page.getByRole("button", { name: "Добавить в shortlist" });
  const availablePrograms = await shortlistButtons.count();
  expect(availablePrograms).toBeGreaterThanOrEqual(2);
  await shortlistButtons.nth(0).click();
  await expect(page.getByRole("button", { name: "Убрать из shortlist" })).toHaveCount(1, { timeout: 30_000 });
  await expect.poll(() => shortlistButtons.count(), { timeout: 30_000 }).toBe(availablePrograms - 1);
  await page.getByRole("button", { name: "Добавить в shortlist" }).first().click();
  await expect(page.getByRole("button", { name: "Убрать из shortlist" })).toHaveCount(2, { timeout: 30_000 });

  await page.goto("/?view=compare");
  await expect(page.getByTestId("compare-page")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("comparison-table")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("comparison-area-chart")).toBeVisible();

  await page.goto("/?view=admission");
  await expect(page.getByTestId("admission-page")).toBeVisible({ timeout: 30_000 });
  const removeSubject = page.getByRole("button", { name: "Удалить предмет" });
  await removeSubject.nth(2).click();
  await expect(removeSubject).toHaveCount(2);
  await removeSubject.nth(1).click();
  await expect(removeSubject).toHaveCount(1);
  await page.getByRole("spinbutton", { name: "0–100" }).fill("90");
  await page.getByRole("button", { name: "Проверить варианты" }).click();
  await expect(page.getByTestId("admission-outcomes")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Важно про результат")).toBeVisible();

  await page.goto("/?view=decision");
  await expect(page.getByTestId("decision-page")).toBeVisible({ timeout: 30_000 });
  const finalChoice = page.getByTestId("final-choice-card");
  await finalChoice.getByRole("button", { name: "Выбрать эту программу" }).first().click();
  await finalChoice.getByRole("button", { name: "Подтвердить" }).click();
  await expect(finalChoice).toContainText("Вы выбрали", { timeout: 30_000 });
  await page.reload();
  await expect(page.getByTestId("final-choice-card")).toContainText("Вы выбрали", { timeout: 30_000 });

  await completeProftest(page);
  await expect.poll(() => page.getByTestId("proftest-result-card").count(), { timeout: 30_000 }).toBeGreaterThanOrEqual(2);
  await expect(page.getByTestId("proftest-decision-handoff")).toContainText("Сохранённые варианты не изменены автоматически");

  await page.goto("/?view=recommendations");
  await expect(page.getByTestId("recommendations-page")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Предложения системы").first()).toBeVisible();
  const explanation = page.getByText("Почему включено").first();
  const honestEmpty = page.getByText("Кандидаты пока не сформированы.").first();
  await expect(explanation.or(honestEmpty)).toBeVisible({ timeout: 30_000 });
});

async function completeProftest(page: Page): Promise<void> {
  await page.goto("/?view=proftest");
  await expect(page.getByTestId("proftest-intro")).toBeVisible({ timeout: 30_000 });
  await page.getByTestId("proftest-start").click();
  await expect(page.getByTestId("proftest-question")).toBeVisible({ timeout: 30_000 });

  for (let step = 0; step < 9; step += 1) {
    const results = page.getByTestId("proftest-results");
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
    const responsePromise = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/proftest/sessions/current/next"),
      { timeout: 30_000 },
    );
    await next.click();
    const response = await responsePromise;
    expect(response.ok()).toBe(true);
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

  if (!await page.getByTestId("proftest-results").isVisible().catch(() => false)) {
    const complete = page.getByTestId("proftest-complete");
    if (await complete.isVisible().catch(() => false)) await complete.click();
  }
  await expect(page.getByTestId("proftest-results")).toBeVisible({ timeout: 30_000 });
}
