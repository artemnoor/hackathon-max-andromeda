import { expect, test, type Page } from "@playwright/test";

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1)).toBe(true);
}

test("critical applicant screens fit a narrow viewport and keep landmarks visible", async ({ page }) => {
  test.setTimeout(120_000);

  await page.goto("/?view=catalog");
  await expect(page.getByTestId("catalog-page")).toBeVisible({ timeout: 30_000 });
  await expectNoHorizontalOverflow(page);
  await page.getByRole("button", { name: "Открыть", exact: true }).first().click();
  await expect(page.getByTestId("program-page")).toBeVisible({ timeout: 30_000 });
  await expectNoHorizontalOverflow(page);

  for (const [view, testId] of [["compare", "compare-page"], ["admission", "admission-page"], ["recommendations", "recommendations-page"], ["proftest", "proftest-intro"]] as const) {
    await page.goto(`/?view=${view}`);
    await expect(page.getByTestId(testId)).toBeVisible({ timeout: 30_000 });
    await expectNoHorizontalOverflow(page);
  }
});
