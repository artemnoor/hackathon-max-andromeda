import { expect, test } from "@playwright/test";

test("guest can start and complete the production proftest session", async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto("/?view=proftest");
  await expect(page.getByTestId("proftest-intro")).toBeVisible();
  await expect(page.getByTestId("proftest-intro")).toContainText("≈10 вопросов");
  await expect(page.getByTestId("proftest-intro")).toContainText("3 минуты");
  await page.getByTestId("proftest-start").click();
  await expect(page.getByTestId("proftest-question")).toBeVisible();

  const question = page.getByTestId("proftest-question");
  const results = page.getByTestId("proftest-results");
  for (let step = 0; step < 9; step += 1) {
    if (await results.isVisible().catch(() => false)) break;
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
    const previousQuestionId = await question.getAttribute("data-question-id");
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
      break;
    }
    await expect.poll(async () => {
      if (await results.isVisible().catch(() => false)) return "results";
      const nextQuestionId = await question.getAttribute("data-question-id").catch(() => null);
      return nextQuestionId && nextQuestionId !== previousQuestionId ? nextQuestionId : "pending";
    }, { timeout: 15_000, intervals: [100, 250, 500, 1_000] }).not.toBe("pending");
  }

  await expect(results).toBeVisible();
  await expect(page.getByTestId("proftest-result-card").first()).toBeVisible();
  expect(await page.getByTestId("proftest-question").count()).toBe(0);
});

test("proftest restores the current question after reload", async ({ page }) => {
  await page.goto("/?view=proftest");
  await page.getByTestId("proftest-start").click();
  await expect(page.getByTestId("proftest-question")).toBeVisible();
  await page.getByTestId("proftest-option").first().click();
  await page.reload();
  await expect(page.getByTestId("proftest-question")).toBeVisible();
  await expect(page.getByTestId("proftest-option").first()).toHaveAttribute("aria-pressed", "true");
});

test("proftest discards a malformed local draft before starting a session", async ({ page }) => {
  await page.addInitScript(() => {
    window.localStorage.setItem("andromeda:proftest:proftest-v3:session-answers", "{not-json");
  });

  await page.goto("/?view=proftest");
  await expect(page.getByTestId("proftest-intro")).toBeVisible();
  await expect(page.getByTestId("proftest-intro")).toContainText("Начать тест");
  await page.getByTestId("proftest-start").click();
  await expect(page.getByTestId("proftest-question")).toBeVisible();
});

test("proftest offers a retry when session restore fails", async ({ page }) => {
  let intercepted = false;
  await page.route("**/proftest/sessions/current", async (route) => {
    if (!intercepted) {
      intercepted = true;
      await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ code: "SERVICE_UNAVAILABLE", message: "temporary", details: [] }) });
      return;
    }
    await route.continue();
  });

  await page.goto("/?view=proftest");
  await expect(page.getByTestId("proftest-intro")).toBeVisible();
  await expect(page.getByTestId("proftest-intro").getByRole("alert")).toContainText("Не удалось восстановить");
  await expect(page.getByTestId("proftest-start")).toContainText("Повторить");
  await page.getByTestId("proftest-start").click();
  await expect(page.getByTestId("proftest-question")).toBeVisible();
});
