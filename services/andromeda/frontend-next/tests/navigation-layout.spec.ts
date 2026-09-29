import { expect, test } from "@playwright/test";

test("desktop navigation groups stay in separate, visible rows", async ({ page }) => {
  for (const width of [1600, 1440, 1280, 1024]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/", { waitUntil: "domcontentloaded" });

    const primary = page.getByRole("navigation", { name: "Основные разделы", exact: true });
    const secondary = page.getByRole("navigation", { name: "Дополнительные разделы", exact: true });

    await expect(primary).toBeVisible();
    await expect(secondary).toBeVisible();

    const primaryBounds = await primary.boundingBox();
    const secondaryBounds = await secondary.boundingBox();
    expect(primaryBounds, `primary navigation at ${width}px`).not.toBeNull();
    expect(secondaryBounds, `secondary navigation at ${width}px`).not.toBeNull();
    console.log("[FIX:app-shell-nav] viewport geometry", {
      viewportWidth: width,
      primaryWidth: primaryBounds?.width,
      primaryBottom: primaryBounds ? primaryBounds.y + primaryBounds.height : null,
      secondaryTop: secondaryBounds?.y,
    });
    expect(primaryBounds!.width, `primary navigation width at ${width}px`).toBeGreaterThan(0);
    expect(
      secondaryBounds!.y,
      `secondary navigation must follow the primary row at ${width}px`,
    ).toBeGreaterThanOrEqual(primaryBounds!.y + primaryBounds!.height - 1);

    for (const button of await primary.getByRole("button").all()) {
      const bounds = await button.boundingBox();
      expect(bounds, `primary button at ${width}px`).not.toBeNull();
      expect(bounds!.x, `primary button left edge at ${width}px`).toBeGreaterThanOrEqual(primaryBounds!.x - 1);
      expect(bounds!.x + bounds!.width, `primary button right edge at ${width}px`).toBeLessThanOrEqual(
        primaryBounds!.x + primaryBounds!.width + 1,
      );
    }
  }
});

test("mobile navigation scrolls inside the viewport without page overflow", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium");
  await page.goto("/?view=assistant", { waitUntil: "domcontentloaded" });

  const secondary = page.getByRole("navigation", {
    name: "Дополнительные разделы (мобильное)",
    exact: true,
  });
  await expect(secondary).toBeVisible();
  const before = await secondary.evaluate((element) => element.scrollLeft);
  await secondary.hover();
  await page.mouse.wheel(260, 0);
  await expect.poll(() => secondary.evaluate((element) => element.scrollLeft)).toBeGreaterThan(before);

  const widths = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    document: document.documentElement.scrollWidth,
    bodyFont: getComputedStyle(document.body).fontFamily,
    headingFont: getComputedStyle(document.querySelector("h1")!).fontFamily,
    googleFontRequests: performance
      .getEntriesByType("resource")
      .filter((entry) => /fonts\.(googleapis|gstatic)\.com/.test(entry.name)).length,
  }));
  console.log("[FIX:app-shell-nav] mobile document geometry", widths);
  expect(widths.document).toBeLessThanOrEqual(widths.viewport);
  expect(widths.bodyFont).toContain("Segoe UI");
  expect(widths.headingFont).toContain("Georgia");
  expect(widths.googleFontRequests).toBe(0);
});

test("mobile assistant question and send controls fit in the initial viewport", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "mobile-chromium");
  await page.goto("/?view=assistant", { waitUntil: "domcontentloaded" });

  const question = page.getByRole("textbox", { name: "Вопрос к Andromeda" });
  const send = page.getByRole("button", { name: "Отправить вопрос" });
  await expect(question).toBeVisible();
  await expect(send).toBeVisible();

  const controls = await Promise.all([question.boundingBox(), send.boundingBox()]);
  const viewportHeight = await page.evaluate(() => document.documentElement.clientHeight);
  console.log("[FIX:assistant-mobile-fit] initial control geometry", {
    viewportHeight,
    questionBottom: controls[0] ? controls[0].y + controls[0].height : null,
    sendBottom: controls[1] ? controls[1].y + controls[1].height : null,
  });
  expect(controls[0]).not.toBeNull();
  expect(controls[1]).not.toBeNull();
  expect(controls[0]!.y + controls[0]!.height).toBeLessThanOrEqual(viewportHeight);
  expect(controls[1]!.y + controls[1]!.height).toBeLessThanOrEqual(viewportHeight);
});
