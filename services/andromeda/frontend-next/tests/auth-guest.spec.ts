import { expect, test } from "@playwright/test";

test("guest can continue without creating an account", async ({ page }) => {
  await page.goto("/?view=catalog");
  await expect(page.getByTestId("profile-menu-trigger")).toBeVisible();
  await page.getByTestId("profile-menu-trigger").click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await expect(page.getByText("Гостевая сессия уже активна")).toBeVisible();
  await page.getByTestId("auth-guest").click();
  await expect(page.getByRole("dialog")).toBeHidden();
  await expect(page.getByTestId("catalog-page")).toBeVisible();
});

test("profile icon supports registration and logout", async ({ page }, testInfo) => {
  const email = `next-${testInfo.project.name}-${Date.now()}@example.com`;
  const password = "a-secure-next-browser-password";

  await page.goto("/?view=catalog");
  await page.getByTestId("profile-menu-trigger").click();
  await page.getByTestId("auth-register-trigger").click();
  await page.locator('[data-testid="auth-email"]:visible').fill(email);
  await page.locator('[data-testid="auth-password"]:visible').fill(password);
  await page.getByTestId("auth-submit").click();

  await expect(page.getByTestId("account-page")).toBeVisible();
  await page.getByTestId("profile-menu-trigger").click();
  await expect(page.getByTestId("auth-account")).toHaveText(email);
  await page.getByTestId("auth-logout").click();
  await expect(page.getByTestId("profile-menu-trigger")).toBeVisible();
});
