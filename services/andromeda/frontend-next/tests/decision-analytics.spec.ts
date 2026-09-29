import { expect, test } from "@playwright/test";

test.describe("decision analytics", () => {
  test("analytics outage never blocks shortlist actions", async ({ page }) => {
    test.setTimeout(120_000);
    await page.route("**/decision/analytics", async (route) => {
      await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ message: "telemetry unavailable" }) });
    });

    await page.goto("/?view=catalog");
    await expect(page.getByTestId("catalog-page")).toBeVisible();
    const add = page.getByRole("button", { name: "Добавить в shortlist" }).first();
    await expect(add).toBeVisible({ timeout: 30_000 });
    await add.click();
    await expect(page.getByRole("button", { name: "Убрать из shortlist" }).first()).toBeVisible();

    await page.getByRole("button", { name: "Убрать из shortlist" }).first().click();
    await expect(page.getByRole("button", { name: "Вернуть в shortlist" }).first()).toBeVisible();
    await page.getByRole("button", { name: "Вернуть в shortlist" }).first().click();
    await expect(page.getByRole("button", { name: "Убрать из shortlist" }).first()).toBeVisible();
  });

  test("view events use safe payloads and remain non-blocking", async ({ page }) => {
    test.setTimeout(120_000);
    const events: Array<{ eventId: string; eventType: string; payload?: Record<string, unknown> }> = [];
    await page.route("**/decision/analytics", async (route) => {
      const body = route.request().postDataJSON() as { eventId: string; eventType: string; payload?: Record<string, unknown> };
      events.push(body);
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ accepted: 1 }) });
    });

    await page.goto("/?view=decision");
    await expect(page.getByTestId("decision-page")).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => events.map((event) => event.eventType)).toContain("decision_session_started");
    await expect.poll(() => events.map((event) => event.eventType)).toContain("shortlist_returned_to");

    await page.goto("/?view=compare");
    await expect(page.getByTestId("compare-page")).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("comparison-summary")).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => events.map((event) => event.eventType)).toContain("comparison_started");
    await expect.poll(() => events.map((event) => event.eventType)).toContain("comparison_completed");

    await page.goto("/?view=admission");
    await expect(page.getByTestId("admission-page")).toBeVisible({ timeout: 30_000 });
    const scoreInputs = page.locator('input[type="number"]');
    await scoreInputs.nth(2).fill("80");
    await scoreInputs.nth(3).fill("80");
    await scoreInputs.nth(4).fill("80");
    await page.getByRole("button", { name: "Проверить варианты" }).click();
    await expect(page.getByTestId("admission-outcomes")).toBeVisible({ timeout: 30_000 });
    await expect.poll(() => events.map((event) => event.eventType)).toContain("admission_fit_viewed");

    const forbiddenKeys = new Set(["email", "cookie", "score", "profile", "sourceBody", "shortlistSizeBefore", "shortlistSizeAfter"]);
    for (const event of events) {
      expect(event.eventId).toMatch(/^decision-event:[0-9a-f]{32}$/);
      for (const key of Object.keys(event.payload ?? {})) expect(forbiddenKeys.has(key)).toBe(false);
      if (event.payload?.programId) expect(event.payload.programId).toMatch(/^program:(?:[a-z0-9][a-z0-9-]{1,31}:)?[0-9]{2}\.[0-9]{2}\.[0-9]{2}-[0-9]{2,3}$/);
      if (event.payload?.programIds) expect((event.payload.programIds as string[]).length).toBeLessThanOrEqual(3);
    }
  });
});
