import { expect, test } from "@playwright/test";

test("legacy flow URL opens the shared choice dashboard without a funnel", async ({ page }) => {
  await page.goto("/?view=flow");

  await expect(page.getByTestId("legacy-flow-compat")).toBeVisible();
  await expect(page.getByTestId("decision-page")).toBeVisible();
  await expect(page.getByText("Этот сохранённый адрес теперь открывает «Мой выбор»")).toBeVisible();
  await expect(page.getByText("Сценарий абитуриента")).toHaveCount(0);
  await expect(page.getByText("Построить маршрут")).toHaveCount(0);
  await expect(page.getByTestId("proftest-start")).toHaveCount(0);
});
