import { expect, test } from "@playwright/test";

const accessToken = "visual-baseline-access-token";

test.use({ viewport: { width: 1440, height: 1000 } });

test.beforeEach(async ({ page }) => {
  await page.goto(`/#${accessToken}`);
  await expect(page.getByText("Đã kết nối", { exact: true })).toBeVisible();
});

test("restores the legacy account overview, filters, and card hierarchy", async ({
  page,
}) => {
  await expect(page.getByText("Tổng tài khoản", { exact: true })).toHaveCount(0);
  await expect(page.getByText("Tự làm mới", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", {
    name: "Tổng tài khoản: 3",
    exact: true,
  })).toBeVisible();
  await expect(page.getByText("1 tài khoản cần xử lý", { exact: true }))
    .toHaveCount(0);
  await page.getByRole("button", {
    name: "Chi tiết trạng thái tài khoản",
  }).click();
  const statusDetails = page.getByRole("dialog", {
    name: "Chi tiết trạng thái tài khoản",
  });
  await expect(statusDetails.getByText("1 tài khoản cần xử lý", {
    exact: true,
  })).toBeVisible();
  await expect(statusDetails.getByText("Tự làm mới", { exact: true }))
    .toBeVisible();
  await expect(statusDetails.getByText("Cập nhật gần nhất", { exact: true }))
    .toBeVisible();
  await expect(statusDetails.getByText("2 / 3", { exact: true })).toBeVisible();
  await statusDetails.getByRole("button", { name: "Đóng" }).click();

  const alphaCard = page.getByRole("article").filter({
    hasText: "alpha@example.test",
  });
  await expect(alphaCard.getByText("Plus", { exact: true })).toBeVisible();
  await expect(alphaCard.getByText("Đề xuất sử dụng", { exact: true }))
    .toBeVisible();
  await expect(alphaCard.getByText(/Còn 24 giây/)).toBeVisible();
  const quotaWindows = alphaCard.locator(".quota-window");
  await expect(quotaWindows).toHaveCount(2);
  await expect(quotaWindows.nth(0)).toContainText("5 giờ");
  await expect(quotaWindows.nth(0)).toContainText("82%");
  await expect(quotaWindows.nth(1)).toContainText("Weekly");
  await expect(quotaWindows.nth(1)).toContainText("64%");
  const quotaResets = alphaCard.locator(".quota-reset-row");
  await expect(quotaResets).toHaveCount(2);
  await expect(quotaResets.nth(0)).toContainText("23/07 14:00");
  await expect(quotaResets.nth(1)).toContainText("28/07 09:00");
  await expect(alphaCard.getByText("23/07 09:45", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: /Lọc tài khoản/ }).click();
  await page.getByRole("dialog", { name: "Lọc tài khoản" })
    .getByLabel("Quota còn", { exact: true }).check();
  await expect(alphaCard).toBeVisible();
  await expect(page.getByText("beta@example.test", { exact: true })).toBeVisible();
  await expect(page.getByText("gamma@example.test", { exact: true })).toBeHidden();

  await alphaCard.getByRole("button", { name: "Tùy chọn" }).click();
  await expect(alphaCard.getByRole("menuitem", { name: /Đồng bộ/ })).toBeVisible();
  await expect(alphaCard.getByRole("menuitem", { name: /Ngắt liên kết/ }))
    .toBeVisible();
  await expect(alphaCard.locator('[data-action="reset-profile"]')).toHaveCount(0);
  await expect(alphaCard.getByRole("menuitem", {
    name: "Chỉnh sửa mật khẩu",
  })).toBeVisible();
  await expect(alphaCard.getByRole("menuitem", { name: /Xóa tài khoản/ }))
    .toBeVisible();

  await alphaCard.getByRole("menuitem", {
    name: "Chỉnh sửa mật khẩu",
  }).click();
  const passwordDialog = page.getByRole("dialog", {
    name: "Chỉnh sửa mật khẩu",
  });
  await expect(passwordDialog).toContainText(
    "không đổi mật khẩu OpenAI/ChatGPT",
  );
  await passwordDialog.getByLabel(/Mật khẩu mới/).fill("new-password");
  await passwordDialog.getByRole("button", { name: "Lưu" }).click();
  await expect(passwordDialog).toBeHidden();
  await expect(page.getByRole("status")).toContainText(
    "Đã cập nhật mật khẩu đã lưu.",
  );
});

test("checks and adds one account without a preview step", async ({ page }) => {
  await page.getByRole("button", { name: "Thêm tài khoản" }).click();
  const dialog = page.getByRole("dialog", { name: "Thêm tài khoản" });
  const input = dialog.getByLabel(
    "Nhập một tài khoản theo định dạng: email|password|secret",
  );
  await expect(input).toHaveAttribute(
    "placeholder",
    "user@example.com|password|TOTP_SECRET",
  );
  await expect(dialog.getByRole("button", { name: "Xem trước" })).toHaveCount(0);
  const status = dialog.locator("#account-check");
  await expect(status).toBeEmpty();

  const add = dialog.getByRole("button", { name: "Thêm", exact: true });
  await input.fill(
    "alpha@example.test|new-password|JBSWY3DPEHPK3PXP",
  );
  await expect(dialog.getByText("Email đã tồn tại.", { exact: true }))
    .toBeVisible();
  await expect(status).toHaveClass(/error/);
  const mutedColor = await page.evaluate(() => {
    const probe = document.createElement("span");
    probe.style.color = "var(--muted)";
    document.body.append(probe);
    const color = getComputedStyle(probe).color;
    probe.remove();
    return color;
  });
  const errorColor = await status.evaluate(
    (element) => getComputedStyle(element).color,
  );
  expect(errorColor).not.toBe(mutedColor);
  await expect(add).toBeDisabled();

  await input.fill(
    "delta@example.test|password|KRUGS4ZANFZSAYJA",
  );
  await expect(dialog.getByText("Tài khoản có thể được thêm.", { exact: true }))
    .toBeVisible();
  await expect(status).toHaveClass(/success/);
  const successColor = await status.evaluate(
    (element) => getComputedStyle(element).color,
  );
  expect(successColor).not.toBe(mutedColor);
  expect(successColor).not.toBe(errorColor);
  await expect(add).toBeEnabled();
  await add.click();
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("status")).toContainText(
    "Đã thêm delta@example.test.",
  );
});

test("restores all-account and single-account usage parity", async ({ page }) => {
  await page.getByRole("tab", { name: "Sử dụng" }).click();
  await expect(page.locator("section[aria-label='Sử dụng token']")).toBeVisible();
  const usageTable = page.getByRole("table", {
    name: "Thống kê quota theo từng tài khoản",
  });
  for (const heading of [
    "Tài khoản",
    "Gói",
    "Lifetime",
    "Peak/ngày",
    "Longest task",
    "Current streak",
    "Longest streak",
    "Quota còn lại",
    "Trạng thái",
    "Reset quota",
    "Đồng bộ cuối",
  ]) {
    await expect(
      usageTable.getByRole("columnheader", { name: heading }),
    ).toBeVisible();
  }
  await expect(usageTable.getByText("alpha@example.test", { exact: true }))
    .toBeVisible();
  await expect(usageTable.getByText("gamma@example.test", { exact: true }))
    .toBeVisible();
  const alignments = async (selector: string) => usageTable.locator(selector)
    .evaluateAll((cells) => [...new Set(cells.map(
      (cell) => getComputedStyle(cell).textAlign,
    ))]);
  expect(await alignments("th, td:not(:first-child)")).toEqual(["center"]);
  expect(await alignments("td:first-child")).toEqual(["left"]);

  const dailyCells = page.locator(".heat-cell");
  await expect.poll(() => dailyCells.count()).toBeGreaterThanOrEqual(365);
  const activeCell = page.locator(".heat-cell[tabindex='0']");
  await expect(activeCell).toHaveCount(1);
  await activeCell.hover();
  const tooltip = page.locator("#heatmap-pointer-tooltip");
  await expect(tooltip).toBeVisible();
  await expect(tooltip).toHaveText(await activeCell.getAttribute("aria-label") ?? "");
  await expect(page.locator("#heatmap-tooltip")).toHaveCount(0);
  await expect(activeCell).not.toHaveAttribute("title", /.+/);
  expect(await tooltip.evaluate((element) => element.parentElement === document.body))
    .toBe(true);
  const cellBox = await activeCell.boundingBox();
  const tooltipBox = await tooltip.boundingBox();
  if (!cellBox || !tooltipBox) throw new Error("Expected heatmap geometry");
  const pointerX = cellBox.x + cellBox.width / 2;
  const pointerY = cellBox.y + cellBox.height / 2;
  const horizontalGap = Math.min(
    Math.abs(tooltipBox.x - pointerX),
    Math.abs(tooltipBox.x + tooltipBox.width - pointerX),
  );
  expect(horizontalGap).toBeLessThanOrEqual(16);
  expect(Math.abs(tooltipBox.y + tooltipBox.height - (pointerY - 12)))
    .toBeLessThanOrEqual(2);
  await activeCell.focus();
  const firstDate = await activeCell.getAttribute("data-start-date");
  await activeCell.press("ArrowLeft");
  const nextDate = await page.locator(".heat-cell:focus").getAttribute(
    "data-start-date",
  );
  expect(nextDate).not.toBe(firstDate);

  await page.getByRole("button", { name: /Phạm vi tài khoản/ }).click();
  await page.getByRole("dialog", { name: "Phạm vi tài khoản" })
    .getByLabel("alpha@example.test").check();
  const usagePanel = page.locator("#usage-panel");
  await expect(
    usagePanel.getByRole("heading", { name: "alpha@example.test" }),
  ).toBeVisible();
  await expect(usagePanel.getByText("Peak tokens", { exact: true })).toBeVisible();
  await expect(usagePanel.getByText("37.000", { exact: true })).toBeVisible();
  await expect(
    usagePanel.getByText("Quota còn lại", { exact: true }),
  ).toBeVisible();
});

test("never overlaps token-usage requests", async ({ page }) => {
  let requestCount = 0;
  let inFlight = 0;
  let maximumInFlight = 0;
  await page.route("**/api/usage/tokens", async (route) => {
    requestCount += 1;
    inFlight += 1;
    maximumInFlight = Math.max(maximumInFlight, inFlight);
    await new Promise((resolve) => setTimeout(resolve, 150));
    const response = await route.fetch();
    await route.fulfill({ response });
    inFlight -= 1;
  });

  await page.getByRole("tab", { name: "Sử dụng" }).click();
  await expect(page.locator("section[aria-label='Sử dụng token']")).toBeVisible();
  await page.getByRole("button", { name: "Làm mới dữ liệu" }).click();
  await expect.poll(() => requestCount).toBe(2);
  await expect.poll(() => inFlight).toBe(0);
  expect(maximumInFlight).toBe(1);
  await page.unrouteAll({ behavior: "wait" });
});

test("disables an action while in flight and surfaces generic failures", async ({
  page,
}) => {
  await page.route("**/api/codex/refresh", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 250));
    await route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ detail: "Internal fixture detail" }),
    });
  });

  const refresh = page.getByRole("button", { name: "Làm mới tất cả" });
  await refresh.click();
  await expect(refresh).toBeDisabled();
  const alert = page.getByRole("alert");
  await expect(alert).toContainText(/Không thể/);
  await expect(alert).not.toContainText("Internal fixture detail");
});
