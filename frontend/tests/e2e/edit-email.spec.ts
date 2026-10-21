import { expect, test } from "@playwright/test";

import { applicationState } from "../../src/test/fixtures.ts";

test.use({ contextOptions: { reducedMotion: "reduce" } });

test("retries an email save and keeps the mismatched account visible for relinking", async ({ page }) => {
  test.setTimeout(60_000);
  await page.addInitScript(() => window.localStorage.setItem("otp-codex-effects", "off"));
  let state = applicationState();
  const original = state.accounts[0]!;
  state = { ...state, accounts: [original] };
  const updatedEmail = "edited@example.test";
  const writeError = "Không thể ghi dữ liệu tài khoản. Hãy kiểm tra quyền ghi file accounts.json.";
  const mutations: string[] = [];
  let saves = 0;

  await page.route(/\/api\/(bootstrap|state)$/, async (route) => {
    const response = await route.fetch();
    const data = await response.json();
    await route.fulfill({ response, json: data.state ? { ...data, state } : state });
  });
  await page.route(`/api/accounts/${original.id}/email`, async (route) => {
    expect(route.request().method()).toBe("PATCH");
    expect(route.request().postDataJSON()).toEqual({ email: updatedEmail });
    mutations.push("email");
    saves += 1;
    if (saves === 1) {
      await route.fulfill({ status: 409, headers: { "X-OTP-Codex-App": "1" }, json: { detail: writeError } });
      return;
    }
    state = { ...state, accounts: [{
      ...original, email: updatedEmail, plan_type: "—", quota_remaining: "—",
      quota_windows: [], account_state: "Sai tài khoản Codex",
      sync_status: "Email Codex khác – bấm Liên kết Codex",
    }] };
    await route.fulfill({ json: { updated: true, id: original.id, email: updatedEmail } });
  });
  await page.route(`/api/codex/${original.id}/login`, async (route) => {
    mutations.push("login");
    await route.fulfill({ json: { accepted: true } });
  });
  page.on("request", (request) => {
    if (request.method() === "DELETE") mutations.push("delete");
  });

  await page.goto("/#visual-baseline-access-token");
  const plusFilter = page.getByRole("button", { name: /^Plus/ });
  await plusFilter.click();
  await expect(plusFilter).toHaveAttribute("aria-pressed", "true");
  const card = page.locator(`#account-${original.id}`);
  await card.locator('[data-action="options"]').click();
  await card.getByRole("menuitem", { name: "Chỉnh sửa email" }).click();
  const dialog = page.getByRole("dialog", { name: "Chỉnh sửa email" });
  await expect(dialog).toContainText("không đổi email đăng nhập OpenAI");
  await dialog.getByRole("textbox", { name: /Email mới thay cho/ }).fill(updatedEmail);
  await dialog.getByRole("button", { name: "Lưu", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText(writeError);
  await expect(dialog).toBeVisible();
  await expect(card.locator(".account-email")).toHaveText(original.email);
  await expect(plusFilter).toHaveAttribute("aria-pressed", "true");

  await dialog.getByRole("button", { name: "Lưu", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(card).toBeVisible();
  await expect(card.locator(".account-email")).toHaveText(updatedEmail);
  await expect(card.locator(".plan-badge")).toHaveText("—");
  await expect(card.locator(".quota-progress")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /Tất cả gói/ })).toHaveAttribute("aria-pressed", "true");
  await card.locator('[data-action="options"]').click();
  await card.getByRole("menuitem", { name: "Đăng nhập lại", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Đã mở quy trình đăng nhập.");
  expect(mutations).toEqual(["email", "email", "login"]);
});
