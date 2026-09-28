import { expect, test } from "@playwright/test";

test("events remain optional and expose only source-backed program relations", async ({ page }) => {
  await page.goto("/?view=events");
  await expect(page.getByText("События университетов")).toBeVisible();

  // The fixture contains an official event without a program relation. The UI
  // explains the source gap instead of inventing an add-to-shortlist action.
  await expect(page.getByTestId("event-source-gap")).toBeVisible();
  const unlinkedCard = page.locator('[data-slot="card"]').filter({ hasText: "Университетский день исследований" }).first();
  await expect(unlinkedCard.getByRole("button", { name: "Добавить в shortlist" })).toHaveCount(0);

  // A linked event offers an explicit program action from canonical data.
  const linkedCard = page.locator('[data-slot="card"]').filter({ hasText: "День открытых дверей ИУ" }).first();
  await expect(linkedCard.getByRole("button", { name: "Добавить в shortlist" })).toBeVisible();
  await linkedCard.getByRole("button", { name: "День открытых дверей ИУ" }).click();
  await expect(page.getByText("Связанные программы")).toBeVisible();
  await expect(page.getByRole("button", { name: "Добавить в shortlist" }).first()).toBeVisible();
});

test("personal route is an optional support surface for a guest", async ({ page }) => {
  await page.goto("/?view=personal-route");
  await expect(page.getByTestId("personal-route-empty")).toBeVisible();
  await expect(page.getByText("профтест не требуется", { exact: false })).toBeVisible();
  await expect(page.getByText("пошаговый план действий", { exact: false })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Открыть «Мой выбор»" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Открыть каталог" })).toBeVisible();
});
