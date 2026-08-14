import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";
import { createRequire } from "node:module";

const accessToken = "visual-baseline-access-token";
const require = createRequire(import.meta.url);
const axePath = require.resolve("axe-core/axe.min.js");

async function seriousAxeViolations(page: Page): Promise<string[]> {
  return page.evaluate(async () => {
    const axe = (window as unknown as {
      axe: {
        run: () => Promise<{
          violations: Array<{ impact: string | null; id: string }>;
        }>;
      };
    }).axe;
    const result = await axe.run();
    return result.violations
      .filter((violation) => ["critical", "serious"].includes(
        violation.impact ?? "",
      ))
      .map((violation) => violation.id);
  });
}

async function visibleGlassOpacity(page: Page): Promise<Array<{
  alpha: number;
  mode: string | null;
  name: string;
}>> {
  return page.locator('[data-glass-version="3"]:visible').evaluateAll(
    (elements) => elements.map((element) => {
      const color = getComputedStyle(element).backgroundColor;
      const alphaMatch = color.match(
        /^rgba?\([^,]+,[^,]+,[^,]+(?:,\s*([\d.]+))?\)$/,
      );
      return {
        alpha: alphaMatch?.[1] === undefined
          ? 1
          : Number(alphaMatch[1]),
        mode: element.getAttribute("data-glass-mode"),
        name: element.getAttribute("aria-label")
          ?? element.textContent?.trim().slice(0, 40)
          ?? element.tagName,
      };
    }),
  );
}

test("production app preserves parity, accessibility, and glass fallbacks", async ({
  page,
}) => {
  const consoleProblems: string[] = [];
  const failedResponses: string[] = [];
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      consoleProblems.push(message.text());
    }
  });
  page.on("pageerror", (error) => consoleProblems.push(error.message));
  page.on("response", (response) => {
    if (response.status() >= 400) {
      failedResponses.push(`${response.status()} ${response.url()}`);
    }
  });
  await page.addInitScript(() => {
    window.localStorage.setItem("otp-codex-theme", "dark");
  });
  await page.addInitScript({ path: axePath });

  await page.goto(`/#${accessToken}`);
  await expect(page.locator(".account-card")).toHaveCount(3);
  await expect(page.locator(".connection.is-ready"))
    .toHaveCSS("color", "rgb(114, 223, 179)");
  expect(await page.locator("body").evaluate(
    (body) => getComputedStyle(body).backgroundImage,
  )).not.toContain("app-background.avif");
  const alphaCard = page.getByRole("article").filter({
    hasText: "alpha@example.test",
  });
  const accountHeaderLayout = await alphaCard.evaluate((card) => {
    const header = card.querySelector<HTMLElement>(".account-card-header");
    const email = card.querySelector<HTMLElement>(".account-email");
    const status = card.querySelector<HTMLElement>(".status");
    if (!header || !email || !status) return null;
    return {
      columns: getComputedStyle(header).gridTemplateColumns.split(" ").length,
      emailOverflow: getComputedStyle(email).overflow,
      emailTextOverflow: getComputedStyle(email).textOverflow,
      emailWhiteSpace: getComputedStyle(email).whiteSpace,
      statusOverflow: getComputedStyle(status).overflow,
    };
  });
  expect(accountHeaderLayout).toEqual({
    columns: 2,
    emailOverflow: "hidden",
    emailTextOverflow: "ellipsis",
    emailWhiteSpace: "nowrap",
    statusOverflow: "hidden",
  });
  await expect(page.getByText("Đã kết nối", { exact: true })).toBeVisible();
  await expect(page).toHaveURL("http://127.0.0.1:8878/");
  await expect.poll(() => page.evaluate(() => window.location.hash)).toBe("");
  await expect.poll(() => page.evaluate(() => (
    window.sessionStorage.getItem("otp-codex-access-token")
  ))).toBe(accessToken);
  const workspaceTabs = page.getByRole("tablist", {
    name: "Khu vực làm việc",
  });
  const activeLens = workspaceTabs.locator("[data-glass-active-lens]");
  await expect(activeLens).toHaveCSS("position", "absolute");
  expect(await workspaceTabs.evaluate((element) => {
    const lens = element.querySelector("[data-glass-active-lens]");
    return lens
      ? lens.getBoundingClientRect().width / element.getBoundingClientRect().width
      : 0;
  })).toBeCloseTo(1 / 3, 1);

  await page.getByRole("button", { name: /Lọc tài khoản/ }).click();
  await page.getByRole("dialog", { name: "Lọc tài khoản" })
    .getByLabel("Cần chú ý").check();
  await expect(page.locator(".account-card").filter({
    hasText: "gamma@example.test",
  })).toBeVisible();
  await expect(page.locator(".account-card").filter({
    hasText: "alpha@example.test",
  })).toBeHidden();
  await page.getByRole("button", { name: /Lọc tài khoản/ }).click();
  await page.getByRole("dialog", { name: "Lọc tài khoản" })
    .getByLabel("Tất cả", { exact: true }).check();
  const gammaCard = page.getByRole("article").filter({
    hasText: "gamma@example.test",
  });
  await gammaCard.getByRole("button", { name: "Tùy chọn" }).click();
  await expect(gammaCard.getByRole("menuitem", { name: "OTP" })).toBeDisabled();

  const usageTab = page.getByRole("tab", { name: "Sử dụng" });
  await usageTab.click();
  await expect(page.locator("section[aria-label='Sử dụng token']")).toBeVisible();
  await expect(page.locator("#usage-panel")).toHaveCSS("opacity", "1");
  await expect.poll(() => page.locator(".heat-cell").count())
    .toBeGreaterThanOrEqual(365);
  await page.getByRole("button", { name: "Tuần" }).click();
  await expect(page.locator(".heat-cell").first()).toBeVisible();
  await usageTab.press("Home");
  const accountsTab = page.getByRole("tab", { name: "Tài khoản" });
  await expect(accountsTab).toBeFocused();
  await accountsTab.press("End");
  const failoverTab = page.getByRole("tab", { name: "Failover" });
  await expect(failoverTab).toBeFocused();
  await expect(page.locator("#failover-panel")).toHaveCSS("opacity", "1");
  await expect(page.getByText("Trạng thái failover", { exact: true })).toBeVisible();
  expect(await seriousAxeViolations(page)).toEqual([]);

  await page.getByRole("button", { name: "Giao diện" }).click();
  await page.getByLabel("Sáng").check();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByLabel("Tắt").check();
  await expect(page.locator("html")).toHaveAttribute("data-effects", "off");
  await expect(page.locator(".glass-overlay")).toHaveCount(0);
  await expect(page.locator("canvas")).toHaveCount(0);
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator("html")).toHaveAttribute("data-effects", "off");
  expect(failedResponses).toEqual([]);
  expect(consoleProblems).toEqual([]);
  expect(await seriousAxeViolations(page)).toEqual([]);
});

test("uses reclaimed header space for account status details", async ({
  page,
}) => {
  await page.goto(`/#${accessToken}`);
  const card = page.locator(".account-card").first();
  await expect(card).toBeVisible();

  const layout = await card.evaluate((element) => {
    const header = element.querySelector<HTMLElement>(".account-card-header");
    const meters = element.querySelector<HTMLElement>(".account-meter-grid");
    const details = element.querySelectorAll<HTMLElement>(
      ".account-sync-details > div",
    );
    if (!header || !meters || details.length !== 3) return null;
    const headerContentBottom = Math.max(
      ...[...header.children].map(
        (child) => child.getBoundingClientRect().bottom,
      ),
    );
    return {
      headerGap: meters.getBoundingClientRect().top - headerContentBottom,
      detailHeights: [...details].map(
        (detail) => detail.getBoundingClientRect().height,
      ),
    };
  });

  expect(layout).not.toBeNull();
  expect(layout!.headerGap).toBeGreaterThanOrEqual(0);
  expect(layout!.headerGap).toBeLessThanOrEqual(11);
  expect(Math.min(...layout!.detailHeights)).toBeGreaterThanOrEqual(68);
});

test("effects off keeps every active glass interaction surface opaque", async ({
  page,
}) => {
  await page.goto(`/#${accessToken}`);
  await page.getByRole("button", { name: "Giao diện" }).click();
  await page.getByLabel("Tắt", { exact: true }).check();
  await expect(page.locator("html")).toHaveAttribute("data-effects", "off");
  await expect(page.getByRole("dialog", {
    name: "Tùy chỉnh giao diện",
  })).toHaveAttribute("data-glass-mode", "off");

  const assertOpaque = async () => {
    const surfaces = await visibleGlassOpacity(page);
    expect(surfaces.length).toBeGreaterThan(0);
    expect(surfaces.filter((surface) => surface.mode !== "off")).toEqual([]);
    expect(surfaces.filter((surface) => surface.alpha < 0.92)).toEqual([]);
  };

  await assertOpaque();
  await page.keyboard.press("Escape");

  const account = page.locator(".account-card").first();
  await account.getByRole("button", { name: "Tùy chọn" }).click();
  await expect(account.getByRole("menu")).toBeVisible();
  await assertOpaque();
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Thêm tài khoản" }).click();
  await expect(page.getByRole("dialog", {
    name: "Thêm tài khoản",
  })).toBeVisible();
  await assertOpaque();
});

test("keeps account card chrome stable when an email is long", async ({
  page,
}) => {
  const longEmail = "amoeba55kilt+20fable.minted@icloud.com";
  const withLongEmail = (payload: {
    state: { accounts: Array<{ id: string; email: string }> };
  }) => ({
    ...payload,
    state: {
      ...payload.state,
      accounts: payload.state.accounts.map((account) => (
        account.id === "2222222222222222"
          ? { ...account, email: longEmail }
          : account
      )),
    },
  });
  await page.route("**/api/bootstrap", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      body: JSON.stringify(withLongEmail(await response.json())),
    });
  });
  await page.route("**/api/state", async (route) => {
    const response = await route.fetch();
    await route.fulfill({
      response,
      body: JSON.stringify(withLongEmail({ state: await response.json() }).state),
    });
  });

  await page.goto(`/#${accessToken}`);
  await expect(page.locator(".account-card")).toHaveCount(3);

  const shortCard = page.getByRole("article").filter({
    hasText: "alpha@example.test",
  });
  const longCard = page.getByRole("article").filter({
    hasText: longEmail,
  });

  const metrics = await longCard.evaluate((card) => {
    const email = card.querySelector(".account-email") as HTMLElement;
    const status = card.querySelector(".status") as HTMLElement;
    const meters = card.querySelector(".account-meter-grid") as HTMLElement;
    const emailStyle = getComputedStyle(email);
    return {
      emailOverflows: email.scrollWidth > email.clientWidth,
      emailOverflow: emailStyle.overflow,
      emailTextOverflow: emailStyle.textOverflow,
      emailWhiteSpace: emailStyle.whiteSpace,
      meterTop: meters.getBoundingClientRect().top,
      statusWidth: status.getBoundingClientRect().width,
      statusText: status.textContent?.trim(),
      statusWhiteSpace: getComputedStyle(status).whiteSpace,
    };
  });
  const shortMeterTop = await shortCard
    .locator(".account-meter-grid")
    .evaluate((meters) => meters.getBoundingClientRect().top);

  expect(metrics.emailOverflows).toBe(true);
  expect(metrics.emailOverflow).toBe("hidden");
  expect(metrics.emailTextOverflow).toBe("ellipsis");
  expect(metrics.emailWhiteSpace).toBe("nowrap");
  expect(metrics.statusText).toBe("Hoạt động bình thường");
  expect(metrics.statusWhiteSpace).toBe("nowrap");
  expect(metrics.statusWidth).toBeGreaterThanOrEqual(150);
  expect(Math.abs(metrics.meterTop - shortMeterTop)).toBeLessThanOrEqual(2);
});

test("keeps the command layer in document flow while scrolling", async ({
  page,
}) => {
  await page.goto(`/#${accessToken}`);
  await expect(page.locator(".account-card")).toHaveCount(3);
  const commandLayer = page.locator(".app-command-layer");

  await expect(commandLayer).toHaveCSS("position", "relative");
  const initialTop = await commandLayer.evaluate(
    (element) => element.getBoundingClientRect().top,
  );
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await expect.poll(async () => (await commandLayer.evaluate(
    (element) => element.getBoundingClientRect().top,
  )) < initialTop).toBe(true);
});

test("morphs both account selectors and restores trigger focus", async ({
  page,
}) => {
  await page.goto(`/#${accessToken}`);
  await expect(page.locator(".account-card")).toHaveCount(3);

  const accountFilter = page.getByRole("button", {
    name: /Lọc tài khoản/,
  });
  await accountFilter.click();
  const accountDialog = page.getByRole("dialog", {
    name: "Lọc tài khoản",
  });
  await expect(accountDialog).toHaveAttribute(
    "data-glass-morph-id",
    "account-filter",
  );
  await page.getByRole("heading", {
    name: "Tổng tài khoản: 3",
    exact: true,
  }).click();
  await expect(accountDialog).toBeHidden();
  await expect(accountFilter).toBeFocused();

  await accountFilter.click();
  await accountDialog.getByLabel("Cần chú ý").check();
  await expect(accountDialog).toBeHidden();
  await expect(accountFilter).toContainText("Cần chú ý");

  await page.getByRole("tab", { name: "Sử dụng" }).click();
  const usageScope = page.getByRole("button", {
    name: /Phạm vi tài khoản/,
  });
  await usageScope.click();
  const usageDialog = page.getByRole("dialog", {
    name: "Phạm vi tài khoản",
  });
  await expect(usageDialog).toHaveAttribute(
    "data-glass-morph-id",
    "usage-account-scope",
  );
  expect(await usageScope.locator(".glass-select-chevron").evaluate((element) => {
    const marker = getComputedStyle(element);
    return marker.borderRightWidth === "2px"
      && marker.borderBottomWidth === "2px";
  })).toBe(true);
  await expect(usageDialog.locator(".glass-select-options"))
    .toHaveCSS("overflow-y", "auto");
  await expect(usageDialog.locator(".glass-select-options label span").last())
    .toHaveCSS("overflow-wrap", "anywhere");
  await usageDialog.getByLabel("alpha@example.test").check();
  await expect(usageDialog).toBeHidden();
  await expect(usageScope).toContainText("alpha@example.test");
  await expect(usageScope.locator(".glass-select-trigger-label"))
    .toHaveCSS("text-overflow", "ellipsis");
});

test("closes every account popover from its original trigger position", async ({
  page,
}) => {
  await page.goto(`/#${accessToken}`);
  await expect(page.locator(".account-card")).toHaveCount(3);

  const cases = [
    {
      trigger: page.getByRole("button", { name: "Giao diện" }),
      panel: page.getByRole("dialog", { name: "Tùy chỉnh giao diện" }),
    },
    {
      trigger: page.getByRole("button", {
        name: "Chi tiết trạng thái tài khoản",
      }),
      panel: page.getByRole("dialog", {
        name: "Chi tiết trạng thái tài khoản",
      }),
    },
    {
      trigger: page.getByRole("button", { name: /Lọc tài khoản/ }),
      panel: page.getByRole("dialog", { name: "Lọc tài khoản" }),
    },
    {
      trigger: page.locator(".account-card").first().getByRole("button", {
        name: "Tùy chọn",
      }),
      panel: page.locator(".account-card").first().getByRole("menu"),
    },
  ];

  for (const current of cases) {
    const triggerBox = await current.trigger.boundingBox();
    expect(triggerBox).not.toBeNull();
    await current.trigger.click();
    await expect(current.panel).toBeVisible();
    await page.mouse.click(
      triggerBox!.x + triggerBox!.width / 2,
      triggerBox!.y + triggerBox!.height / 2,
    );
    await expect(current.panel).toBeHidden();
  }

  const importSource = page.locator("[data-glass-morph-source='dialog']");
  const importDialog = page.getByRole("dialog", { name: "Thêm tài khoản" });
  await expect(importSource).toHaveAttribute(
    "data-glass-layout-id",
    "import-account-dialog",
  );
  await page.getByRole("button", { name: "Thêm tài khoản" }).click();
  await expect(importDialog).toHaveAttribute(
    "data-glass-layout-id",
    "import-account-dialog",
  );
  await page.getByRole("button", { name: "Hủy" }).click();
  await expect(importDialog).toBeHidden();
});
