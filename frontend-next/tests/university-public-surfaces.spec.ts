import { expect, test } from "@playwright/test";

test("anonymous user can discover a university and open its public catalog", async ({ page }) => {
  await page.goto("/?view=university-catalog");
  await expect(page.getByTestId("university-catalog-page")).toBeVisible();
  const selector = page.getByLabel("Выберите вуз");
  await expect(selector.locator("option")).not.toHaveCount(1);
  await selector.selectOption("university:bmstu");
  await expect(page.getByText("Факультеты и кафедры")).toBeVisible({ timeout: 30_000 });
  await expect(page.getByRole("button", { name: "Афиша вуза" })).toBeVisible();
});

test("public events keep source-backed and university filters separate", async ({ page }) => {
  await page.goto("/?view=events");
  await expect(page.getByText("События университетов")).toBeVisible();
  await expect(page.getByLabel("Афиша конкретного вуза")).toBeVisible();
  await expect(page.getByText("Источник").first()).toBeVisible();
});
