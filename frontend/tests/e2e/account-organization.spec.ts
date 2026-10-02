import { expect, test } from "@playwright/test";

import { applicationState } from "../../src/test/fixtures.ts";

test.use({ contextOptions: { reducedMotion: "reduce" } });

test("uses a flat status-sorted list with hidden Plus expiration and no search", async ({ page }) => {
  test.setTimeout(60_000);
  await page.addInitScript(() => window.localStorage.setItem("otp-codex-theme", "dark"));
  const base = applicationState().accounts[0]!;
  const accounts = [
    { ...base, id: "ready", email: "z-ready@example.test" },
    { ...base, id: "low", email: "a-low@example.test", quota_windows: [], quota_remaining: "12%" },
    { ...base, id: "empty", email: "b-empty@example.test", quota_windows: [
      { ...base.quota_windows[0]!, quota_remaining: "0%" }, base.quota_windows[1]!,
    ] },
    { ...base, id: "team", email: "team@example.test", plan_type: "Business", sync_status: "Cần đăng nhập" },
    { ...base, id: "free", email: "free@example.test", plan_type: "Free" },
    { ...base, id: "other", email: "pro@example.test", plan_type: "Pro", sync_status: "Lỗi tạm thời" },
    applicationState().accounts[1]!,
  ];
  const problems: string[] = [];
  page.on("pageerror", (error) => problems.push(error.message));
  await page.route(/\/api\/(bootstrap|state)$/, async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    const state = data.state ?? data;
    const updated = { ...state, accounts, recommendation: null, sync_status: "Đang đồng bộ" };
    await route.fulfill({ response, json: data.state ? { ...data, state: updated } : updated });
  });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("/#visual-baseline-access-token");
  await expect(page.locator(".account-card")).toHaveCount(7);
  await expect(page.locator(".app-content-header .connection")).toHaveText("Đã kết nối");
  await expect(page.getByRole("button", { name: "Tắt ứng dụng" })).toBeHidden();
  await expect(page.locator("#account-command-actions").getByRole("button", { name: "Làm mới tất cả" })).toBeVisible();
  await page.locator("#account-command-actions").getByRole("button", { name: "Thêm tài khoản" }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".account-plan-group")).toHaveCount(0);
  await expect(page.locator(".account-grid")).toHaveCount(1);
  await expect(page.locator(".subtitle, .account-list-summary")).toHaveCount(0);
  await expect(page.locator(".account-toolbar")).toBeHidden();
  await expect(page.getByRole("searchbox")).toHaveCount(0);
  await expect(page.locator(".account-email").first()).toHaveText("free@example.test");
  await expect(page.getByText("Hết hạn Plus", { exact: true }).filter({ visible: true })).toHaveCount(0);
  await page.locator("#account-ready").getByRole("button", { name: "Tùy chọn" }).click();
  await expect(page.locator('#account-ready [data-action="edit-plus-expiration"]')).toBeHidden();
  await page.keyboard.press("Escape");
  await expect(page.locator("#account-empty .status")).toHaveText("Hết quota");
  await expect(page.locator("#account-team .status")).toHaveText("Cần đăng nhập");
  await expect(page.locator("#account-free")).not.toContainText("Hết hạn Plus");
  for (const width of [1440, 1200, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    const card = page.locator("#account-free");
    const options = card.locator('[data-action="options"]');
    await expect(options.locator(".sr-only")).toHaveCSS("position", "absolute");
    const emailBox = await card.locator('[data-action="email"]').boundingBox();
    const optionsBox = await options.boundingBox();
    expect(optionsBox!.height).toBe(emailBox!.height);
    expect(optionsBox!.y).toBe(emailBox!.y);
    const glyphBox = await options.locator(".account-options-glyph").boundingBox();
    expect(Math.abs(glyphBox!.x + glyphBox!.width / 2 - optionsBox!.x - optionsBox!.width / 2)).toBeLessThan(1);
    expect(await card.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    const commandBox = await page.locator(".app-command-layer").boundingBox();
    for (const button of await page.locator(".app-command-layer button:visible").all()) {
      const box = await button.boundingBox();
      expect(box!.x + box!.width).toBeLessThanOrEqual(commandBox!.x + commandBox!.width + 1);
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: /Team \/ Business/ }).click();
  await expect(page.locator(".account-card")).toHaveCount(1);
  await page.getByRole("button", { name: /Tất cả gói/ }).click();
  await page.screenshot({ path: "test-results/account-organization-dark.png", fullPage: true });
  await page.getByRole("button", { name: "Giao diện" }).click();
  await page.getByLabel("Sáng").check();
  await page.keyboard.press("Escape");
  await page.screenshot({ path: "test-results/account-organization-light.png", fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".account-card")).toHaveCount(7);
  expect(await page.locator(".accounts-shell").evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  expect(problems).toEqual([]);
});
