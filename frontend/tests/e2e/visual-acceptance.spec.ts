import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";
import { resolve } from "node:path";

const accessToken = "visual-baseline-access-token";
const baselineDir = resolve(
  "..",
  "docs",
  "baselines",
  "liquid-glass-v3",
);

type Theme = "light" | "dark";
type Effects = "full" | "reduced" | "off";

async function setAppearance(
  page: Page,
  theme: Theme,
  effects: Effects,
): Promise<void> {
  await page.evaluate(({ nextTheme, nextEffects }) => {
    window.localStorage.setItem(
      "otp-codex-theme-preference",
      nextTheme,
    );
    window.localStorage.setItem("otp-codex-effects", nextEffects);
  }, { nextTheme: theme, nextEffects: effects });
  await page.reload();
  await page.waitForLoadState("networkidle");
  await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
  await expect(page.locator("html")).toHaveAttribute(
    "data-effects",
    effects,
  );
  await expect(page.getByText("Đã kết nối", { exact: true })).toBeVisible();
  await expect(page.locator(".account-card")).toHaveCount(3);
  await page.evaluate(() => new Promise<void>((resolveFrame) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolveFrame()));
  }));
}

function dynamicMasks(page: Page): Locator[] {
  return [
    page.locator(".otp-meter small"),
    page.locator(".usage-freshness"),
    page.locator("[aria-live='polite']"),
  ];
}

async function capture(
  page: Page,
  filename: string,
  fullPage = true,
): Promise<void> {
  const theme = await page.locator("html").getAttribute("data-theme");
  await page.screenshot({
    path: resolve(baselineDir, filename),
    fullPage,
    animations: "disabled",
    mask: dynamicMasks(page),
    maskColor: theme === "dark" ? "#151b26" : "#e4e9ef",
    caret: "hide",
  });
}

test.use({ viewport: { width: 1440, height: 1000 } });

test("captures the Liquid Glass v3 PC visual acceptance matrix", async ({
  page,
}) => {
  await page.goto(`/#${accessToken}`);

  const accountsMatrix: Array<{ theme: Theme; effects: Effects }> = [
    { theme: "dark", effects: "full" },
    { theme: "light", effects: "full" },
    { theme: "dark", effects: "reduced" },
    { theme: "dark", effects: "off" },
  ];
  for (const entry of accountsMatrix) {
    await setAppearance(page, entry.theme, entry.effects);
    await capture(
      page,
      `accounts-${entry.theme}-${entry.effects}-pc.png`,
    );
  }

  for (const theme of ["dark", "light"] as const) {
    await setAppearance(page, theme, "full");
    await page.getByRole("tab", { name: "Sử dụng" }).click();
    await expect.poll(() => page.locator(".heat-cell").count())
      .toBeGreaterThanOrEqual(365);
    await capture(page, `usage-${theme}-full-pc.png`);
  }

  await setAppearance(page, "light", "full");
  await page.getByRole("button", { name: "Giao diện" }).click();
  await expect(
    page.getByRole("dialog", { name: "Tùy chỉnh giao diện" }),
  ).toBeVisible();
  await expect(
    page.getByRole("dialog", { name: "Tùy chỉnh giao diện" }),
  ).toHaveAttribute("data-glass-morph-state", "settled");
  await capture(page, "appearance-popover-light-full-pc.png", false);

  await page.keyboard.press("Escape");
  await setAppearance(page, "dark", "full");
  const account = page.locator(".account-card").filter({
    hasText: "alpha@example.test",
  });
  await account.locator("[data-action='options']").click();
  await expect(account.getByRole("menu")).toBeVisible();
  await expect(account.locator(".glass-popover-panel")).toHaveAttribute(
    "data-glass-morph-state",
    "settled",
  );
  const optionsBox = await account.locator(".glass-popover-panel")
    .boundingBox();
  expect(optionsBox).not.toBeNull();
  expect(optionsBox!.x).toBeGreaterThanOrEqual(0);
  expect(optionsBox!.y).toBeGreaterThanOrEqual(0);
  expect(optionsBox!.x + optionsBox!.width).toBeLessThanOrEqual(1440);
  expect(optionsBox!.y + optionsBox!.height).toBeLessThanOrEqual(1000);
  await capture(page, "options-popover-dark-full-pc.png", false);

  await page.keyboard.press("Escape");
  await setAppearance(page, "light", "full");
  await page.getByRole("button", { name: "Thêm tài khoản" }).click();
  await expect(
    page.getByRole("dialog", { name: "Thêm tài khoản" }),
  ).toBeVisible();
  await expect(
    page.getByRole("dialog", { name: "Thêm tài khoản" }),
  ).toHaveAttribute("data-glass-morph-state", "settled");
  await capture(page, "import-dialog-light-full-pc.png", false);
});

test("captures rest, hover, and pressed states of a reference control", async ({
  page,
}) => {
  await page.goto(`/#${accessToken}`);
  await setAppearance(page, "dark", "full");
  const control = page.getByRole("button", { name: "Giao diện" });
  await expect(control).toBeVisible();

  await control.screenshot({
    path: resolve(baselineDir, "control-rest-dark-full-pc.png"),
    animations: "disabled",
  });
  await control.hover();
  await control.screenshot({
    path: resolve(baselineDir, "control-hover-dark-full-pc.png"),
    animations: "disabled",
  });
  const box = await control.boundingBox();
  expect(box).not.toBeNull();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.mouse.down();
  try {
    await control.screenshot({
      path: resolve(baselineDir, "control-pressed-dark-full-pc.png"),
    });
  } finally {
    await page.mouse.up();
  }
});
