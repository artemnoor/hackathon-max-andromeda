import { expect, test, type Page } from "@playwright/test";

async function openCatalog(page: Page): Promise<void> {
  await page.goto("/?view=catalog");
  await expect(page.getByTestId("catalog-page")).toBeVisible();
  await expect(page.getByText(/Найдено программ:/)).toBeVisible();
}

test("catalog finishes loading and opens a source-backed program", async ({ page }) => {
  await openCatalog(page);
  await expect(page.getByRole("button", { name: "Открыть" }).first()).toBeVisible();
  await page.getByRole("button", { name: "Открыть", exact: true }).first().click();

  await expect(page.getByTestId("program-page")).toBeVisible();
  await expect(page.getByTestId("curriculum-table")).toBeVisible();
  await expect(page.getByText(/дисциплин/).first()).toBeVisible();

  await page.getByRole("tab", { name: "Поступление" }).click();
  await expect(page.getByTestId("admissions-section")).toBeVisible();
  await expect(page.getByText("Вступительные испытания").first()).toBeVisible();
});

test("program detail keeps the card available when optional source reads fail", async ({ page }) => {
  await page.route("**/programs/*/curriculum", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ code: "SOURCE_UNAVAILABLE", message: "curriculum unavailable", details: [] }) });
  });
  await page.route("**/programs/*/admissions", async (route) => {
    await route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ code: "SOURCE_UNAVAILABLE", message: "admissions unavailable", details: [] }) });
  });

  await openCatalog(page);
  await page.getByRole("button", { name: "Открыть", exact: true }).first().click();
  await expect(page.getByTestId("program-page")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Учебный план недоступен" })).toBeVisible();

  await page.getByRole("tab", { name: "Поступление" }).click();
  await expect(page.getByRole("heading", { name: "Условия поступления недоступны" })).toBeVisible();
});

test("comparison keeps category charts and legends available", async ({ page }) => {
  await openCatalog(page);
  const desktopCompare = page.getByTestId("nav-compare");
  if (await desktopCompare.isVisible().catch(() => false)) {
    await desktopCompare.click();
  } else {
    await page.getByTestId("mobile-nav-compare").click();
  }
  await expect(page.getByTestId("program-a")).toBeVisible();
  await expect(page.getByTestId("program-b")).toBeVisible();
  await expect(page.getByTestId("comparison-table")).toBeVisible();
  await expect(page.getByTestId("area-breakdown")).toBeVisible();
  await expect(page.getByTestId("area-pie-a")).toBeVisible();
  await expect(page.getByTestId("area-pie-b")).toBeVisible();
  await expect(page.getByTestId("area-pie-a").getByRole("list", { name: "Легенда программы A" })).toBeVisible();
  await expect(page.getByTestId("area-pie-b").getByRole("list", { name: "Легенда программы B" })).toBeVisible();
});

test("guest can make and keep an explicit final choice", async ({ page }) => {
  await openCatalog(page);
  const addButtons = page.getByRole("button", { name: "Добавить в shortlist" });
  const availablePrograms = await addButtons.count();
  expect(availablePrograms).toBeGreaterThanOrEqual(2);
  await addButtons.first().click();
  await expect.poll(() => addButtons.count(), { timeout: 30_000 }).toBe(availablePrograms - 1);
  await page.getByRole("button", { name: "Добавить в shortlist" }).first().click();
  await page.locator('[data-testid="nav-decision"]:visible, [data-testid="mobile-nav-decision"]:visible').first().click();
  await expect(page.getByTestId("decision-page")).toBeVisible();
  await expect(page.getByText("Финальный выбор")).toBeVisible();
  await page.getByRole("button", { name: "Выбрать эту программу" }).first().click();
  await page.getByRole("button", { name: "Подтвердить" }).click();
  await expect(page.getByTestId("final-choice-card")).toContainText("Вы выбрали");
  await page.reload();
  await expect(page.getByTestId("final-choice-card")).toContainText("Вы выбрали");
});

test("catalog shortlist continues through comparison to the decision dashboard", async ({ page }) => {
  await openCatalog(page);
  const addButtons = page.getByRole("button", { name: "Добавить в shortlist" });
  const availablePrograms = await addButtons.count();
  expect(availablePrograms).toBeGreaterThanOrEqual(2);
  await addButtons.first().click();
  await expect.poll(() => addButtons.count(), { timeout: 30_000 }).toBe(availablePrograms - 1);
  await page.getByRole("button", { name: "Добавить в shortlist" }).first().click();

  await expect(page.getByTestId("catalog-shortlist-next")).toBeVisible();
  await page.getByTestId("catalog-shortlist-next").click();
  await expect(page.getByTestId("compare-page")).toBeVisible();
  await expect(page.getByTestId("program-a")).toBeVisible();
  await expect(page.getByTestId("program-b")).toBeVisible();
  await expect(page.getByTestId("comparison-table")).toBeVisible();

  await page.getByTestId("compare-to-decision").click();
  await expect(page.getByTestId("decision-page")).toBeVisible();
  await expect(page.getByText("Финальный выбор")).toBeVisible();
  await page.getByRole("button", { name: "Выбрать эту программу" }).first().click();
  await page.getByRole("button", { name: "Подтвердить" }).click();
  await expect(page.getByTestId("final-choice-card")).toContainText("Вы выбрали");
});
