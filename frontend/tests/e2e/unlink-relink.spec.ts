import { expect, test } from "@playwright/test";

import { applicationState } from "../../src/test/fixtures.ts";

test.use({ contextOptions: { reducedMotion: "reduce" } });

test("keeps an unlinked Business account visible and offers linking again", async ({ page }) => {
  test.setTimeout(60_000);
  await page.addInitScript(() => window.localStorage.setItem("otp-codex-effects", "off"));
  let state = applicationState();
  const account = { ...state.accounts[0]!, plan_type: "Business" };
  state = { ...state, accounts: [account] };
  const mutations: string[] = [];
  await page.route(/\/api\/(bootstrap|state)$/, async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    await route.fulfill({ response, json: data.state ? { ...data, state } : state });
  });
  await page.route(`/api/codex/${account.id}/unlink`, async (route) => {
    mutations.push("unlink");
    state = { ...state, accounts: [{ ...account, plan_type: "—", quota_remaining: "—",
      quota_windows: [], account_state: "Chưa xác định", sync_status: "Chưa liên kết" }] };
    await route.fulfill({ json: { accepted: true } });
  });
  await page.route(`/api/codex/${account.id}/login`, async (route) => {
    mutations.push("login");
    await route.fulfill({ json: { accepted: true } });
  });
  page.on("request", (request) => {
    if (request.method() === "DELETE") mutations.push("delete");
  });
  page.once("dialog", async (dialog) => {
    expect(dialog.message()).toContain("giữ nguyên");
    await dialog.accept();
  });
  await page.goto("/#visual-baseline-access-token");
  await page.getByRole("button", { name: /Team \/ Business/ }).click();
  const card = page.locator(`#account-${account.id}`);
  await card.locator('[data-action="options"]').click();
  await card.locator('[data-action="unlink"]').click();
  await expect(card).toBeVisible();
  await expect(card.locator(".status")).toHaveText("Chưa liên kết");
  await card.locator('[data-action="options"]').click();
  await expect(card.locator('[data-action="unlink"]')).toHaveCount(0);
  await card.getByRole("menuitem", { name: "Liên kết Codex" }).click();
  await expect(page.getByRole("status")).toContainText("Đã mở quy trình đăng nhập.");
  expect(mutations).toEqual(["unlink", "login"]);
});
