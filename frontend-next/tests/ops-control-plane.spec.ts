import { expect, test } from "@playwright/test";

const opsKey = process.env.PLAYWRIGHT_OPS_API_KEY;

test.describe("configured ingestion operations", () => {
  test.skip(!opsKey, "requires an explicitly configured staging-like ops key");

  test("rejects a wrong key and diagnoses a confirmed fixture retry", async ({ page }) => {
    test.setTimeout(120_000);
    await page.goto("/?view=ops");
    await expect(page.getByText("Операторская консоль")).toBeVisible();

    await page.getByLabel("Ops key").fill("wrong-test-key");
    await page.getByTestId("ops-login").click();
    await expect(page.getByTestId("app-shell").getByRole("alert")).toContainText("Ops API недоступен или неверный ключ");

    await page.getByLabel("Ops key").fill(opsKey!);
    await page.getByTestId("ops-login").click();
    await expect(page.getByRole("heading", { name: "Ingestion runs" })).toBeVisible();
    await expect(page.getByText(/ключ: •+/)).toBeVisible();

    const retryResponse = page.waitForResponse(
      (response) => response.request().method() === "POST" && response.url().includes("/ops/ingestion/runs/retry"),
    );
    page.once("dialog", (dialog) => dialog.accept());
    await page.getByRole("button", { name: "Запустить ingestion" }).click();
    expect((await retryResponse).ok()).toBe(true);
    await expect(page.getByText("Детали run")).toBeVisible({ timeout: 60_000 });
    await expect(page.getByText("Source gaps")).toBeVisible();
  });
});
