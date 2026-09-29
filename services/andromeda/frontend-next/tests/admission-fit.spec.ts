import { expect, test } from "@playwright/test";

test("admission readiness form has no invented scores and rejects an untouched submission", async ({ page }) => {
  await page.goto("/?view=catalog");
  await expect(page.getByTestId("catalog-page")).toBeVisible();
  await page.getByRole("button", { name: "Открыть", exact: true }).first().click();
  await expect(page.getByTestId("program-page")).toBeVisible();

  await page.getByRole("tab", { name: "Оценка готовности" }).click();
  const panel = page.getByTestId("admission-fit-panel");
  await expect(panel).toBeVisible();
  await expect(panel).toContainText("Это не обещание результата и не гарантия зачисления");
  await expect(panel.getByText(/шанс|вероят/i)).toHaveCount(0);
  await expect(panel.getByRole("spinbutton").first()).toHaveValue("");
  await expect(panel).not.toContainText("85");
  await expect(panel).not.toContainText("82");
  await expect(panel).not.toContainText("88");

  await panel.getByRole("button", { name: "Проверить готовность" }).click();
  await expect(panel.getByRole("alert")).toContainText("Добавьте хотя бы один фактический балл");
});

test("decision constraints show source-backed applicability instead of silently filtering", async ({ page }) => {
  await page.goto("/?view=admission");
  await expect(page.getByTestId("admission-page")).toBeVisible();
  await page.getByLabel("Год поступления").fill("2026");
  await page.getByLabel(/Максимальная стоимость/).fill("100000");
  await page.getByLabel(/Город или ограничение/).fill("Москва");
  for (const input of await page.getByLabel("0–100").all()) await input.fill("80");
  await page.getByRole("button", { name: "Проверить варианты" }).click();

  const outcomes = page.getByTestId("admission-outcomes");
  await expect(outcomes).toBeVisible({ timeout: 30_000 });
  await expect(outcomes).toContainText("Проверка ваших условий");
  await expect(outcomes).toContainText(/Стоимость сопоставлена/);
  await expect(outcomes).toContainText(/Место обучения совпадает/);
});
