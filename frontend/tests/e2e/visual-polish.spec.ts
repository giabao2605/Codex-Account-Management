import { expect, test } from "@playwright/test";
import { resolve } from "node:path";

const accessToken = "visual-baseline-access-token";
const baselineDir = resolve(
  "..",
  "docs",
  "baselines",
  "liquid-glass-v3",
);

test.use({ viewport: { width: 1440, height: 1000 } });

test("keeps controls clean and heatmap dense across themes and ranges", async ({
  page,
}) => {
  await page.goto(`/#${accessToken}`);
  await expect(page.getByText("Đã kết nối", { exact: true })).toBeVisible();

  const actionGroup = page.locator(".account-primary-actions").first();
  await expect(actionGroup).toHaveCSS("border-top-width", "0px");
  await expect(actionGroup).toHaveCSS("background-color", "rgba(0, 0, 0, 0)");
  const buttonTransition = await page.locator(".glass-button").first().evaluate(
    (element) => getComputedStyle(element).transitionProperty,
  );
  expect(buttonTransition).toContain("box-shadow");

  await page.evaluate(() => {
    localStorage.setItem("otp-codex-theme-preference", "light");
  });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  const lightTokens = await page.evaluate(() => {
    const styles = getComputedStyle(document.documentElement);
    return {
      deep: styles.getPropertyValue("--surface-deep").trim(),
      raised: styles.getPropertyValue("--surface-raised").trim(),
      bodyTransition: getComputedStyle(document.body).transitionDuration,
    };
  });
  expect(lightTokens.deep).not.toBe(lightTokens.raised);
  expect(lightTokens.deep).not.toBe("");
  expect(lightTokens.raised).not.toBe("");
  expect(lightTokens.bodyTransition).not.toBe("0s");

  await page.getByRole("tab", { name: "Sử dụng" }).click();
  const grid = page.locator(".heatmap-grid");
  const card = page.locator(".heatmap-card");
  const firstCell = grid.locator(".heat-cell").first();
  const dailyGeometry = await Promise.all([
    grid.boundingBox(),
    card.boundingBox(),
    firstCell.boundingBox(),
  ]);
  expect(dailyGeometry.every(Boolean)).toBe(true);
  expect(
    Math.abs(dailyGeometry[2]!.width - dailyGeometry[2]!.height),
  ).toBeLessThanOrEqual(2);
  expect(dailyGeometry[0]!.width).toBeGreaterThanOrEqual(
    dailyGeometry[1]!.width * 0.9,
  );
  const dailyHeight = dailyGeometry[0]!.height;
  const gridBottom = dailyGeometry[0]!.y + dailyHeight;
  const monthLabels = await page.locator(".heatmap-months").boundingBox();
  expect(monthLabels!.y).toBeGreaterThanOrEqual(gridBottom);
  await card.screenshot({
    path: resolve(baselineDir, "heatmap-light-daily-pc.png"),
  });

  for (const mode of ["Tuần", "Tích lũy"]) {
    await page.getByRole("button", { name: mode, exact: true }).click();
    const cells = grid.locator(".heat-cell");
    await expect.poll(() => cells.count()).toBeGreaterThanOrEqual(52);
    await expect(grid.locator(".heat-cell-segment")).toHaveCount(
      (await cells.count()) * 7,
    );
    const rangeBox = await grid.boundingBox();
    expect(rangeBox!.height).toBeGreaterThanOrEqual(dailyHeight * 0.85);
    await card.screenshot({
      path: resolve(
        baselineDir,
        `heatmap-light-${mode === "Tuần" ? "weekly" : "cumulative"}-pc.png`,
      ),
    });
  }
});
