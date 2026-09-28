import { expect, test } from "@playwright/test";

test("recommendations distinguish a service failure from an absent profile", async ({ page }) => {
  await page.route("**/decision/suggestions", async (route) => {
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ code: "SERVICE_UNAVAILABLE", message: "suggestions unavailable", details: [] }),
    });
  });

  await page.goto("/?view=recommendations");
  await expect(page.getByTestId("recommendations-page")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("heading", { name: "Предложения временно недоступны" })).toBeVisible();
  await expect(page.getByText("Профиль пока не заполнен")).toHaveCount(0);
});

test("recommendations render an honest empty result from the decision contract", async ({ page }) => {
  await page.route("**/decision/suggestions", async (route) => {
    const response = await route.fetch();
    const body = await response.json() as Record<string, unknown>;
    body.suggestions = [];
    body.primaryCandidates = [];
    body.alternativeCandidates = [];
    body.ineligibleCandidates = [];
    body.insufficientDataCandidates = [];
    body.missingData = ["profile"];
    await route.fulfill({ response, body: JSON.stringify(body) });
  });

  await page.goto("/?view=recommendations");
  await expect(page.getByTestId("recommendations-page")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText("Кандидаты пока не сформированы.")).toBeVisible();
  await expect(page.getByText(/Не хватает данных: profile/)).toBeVisible();
  await expect(page.getByText("Предложения временно недоступны")).toHaveCount(0);
});
