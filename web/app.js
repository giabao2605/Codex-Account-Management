"use strict";

const ui = {
  themeToggle: document.querySelector("#theme-toggle"),
  themeToggleText: document.querySelector("#theme-toggle-text"),
  themeColor: document.querySelector("#theme-color"),
  connection: document.querySelector("#connection-status"),
  refreshAll: document.querySelector("#refresh-all"),
  accountCount: document.querySelector("#account-count"),
  visibleAccountCount: document.querySelector("#visible-account-count"),
  syncStatus: document.querySelector("#sync-status"),
  syncSuccessRatio: document.querySelector("#sync-success-ratio"),
  syncSuccessCount: document.querySelector("#sync-success-count"),
  syncLoginCount: document.querySelector("#sync-login-count"),
  syncUnlinkedCount: document.querySelector("#sync-unlinked-count"),
  syncErrorCount: document.querySelector("#sync-error-count"),
  refreshInterval: document.querySelector("#refresh-interval"),
  lastUpdated: document.querySelector("#last-updated"),
  accountFilter: document.querySelector("#account-filter"),
  accountDialog: document.querySelector("#account-dialog"),
  openImport: document.querySelector("#open-import"),
  closeImport: document.querySelector("#close-import"),
  cancelImport: document.querySelector("#cancel-import"),
  accountLines: document.querySelector("#account-lines"),
  importAccounts: document.querySelector("#import-accounts"),
  importResult: document.querySelector("#import-result"),
  accountGrid: document.querySelector("#account-grid"),
  emptyState: document.querySelector("#empty-state"),
  toast: document.querySelector("#toast"),
};

const themeStorageKey = "otp-codex-theme";
const tokenStorageKey = "otp-codex-access-token";
const fragmentToken = window.location.hash.slice(1);
if (fragmentToken) {
  window.sessionStorage.setItem(tokenStorageKey, fragmentToken);
}

let accessToken = fragmentToken || window.sessionStorage.getItem(tokenStorageKey) || "";
let csrfToken = "";
let pollInProgress = false;
let toastTimer = 0;
let renderSignature = "";
let currentState = { accounts: [] };

function applyTheme(theme, options = {}) {
  const normalizedTheme = theme === "light" ? "light" : "dark";
  const isDark = normalizedTheme === "dark";
  const nextThemeLabel = isDark
    ? "Chuyển sang giao diện sáng"
    : "Chuyển sang giao diện tối";

  document.documentElement.dataset.theme = normalizedTheme;
  document.documentElement.style.colorScheme = normalizedTheme;
  ui.themeToggle.setAttribute("aria-pressed", String(isDark));
  ui.themeToggle.setAttribute("aria-label", nextThemeLabel);
  ui.themeToggle.title = nextThemeLabel;
  ui.themeToggleText.textContent = isDark ? "Giao diện tối" : "Giao diện sáng";
  ui.themeColor.content = isDark ? "#0b1020" : "#f3f6fc";

  if (options.persist === false) return;
  try {
    window.localStorage.setItem(themeStorageKey, normalizedTheme);
  } catch (_error) {
    // Theme vẫn được áp dụng trong phiên hiện tại nếu trình duyệt chặn lưu trữ.
  }
}

function toggleTheme() {
  const currentTheme = document.documentElement.dataset.theme;
  applyTheme(currentTheme === "dark" ? "light" : "dark");
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function actionButton(label, action, accountId, options = {}) {
  const className = options.className || "button button-secondary";
  const node = element("button", className, label);
  node.type = "button";
  node.dataset.action = action;
  node.dataset.accountId = accountId;
  if (options.field) node.dataset.field = options.field;
  if (options.ariaLabel) node.setAttribute("aria-label", options.ariaLabel);
  return node;
}

function createProgress(className, value, max, label) {
  const node = element("progress", className);
  node.max = max;
  node.value = Math.max(0, Math.min(max, value));
  node.setAttribute("aria-label", label);
  return node;
}

function normalizedStatus(account) {
  return `${account.account_state || ""} ${account.sync_status || ""}`
    .toLocaleLowerCase("vi");
}

function needsAttention(account) {
  const value = normalizedStatus(account);
  return ["lỗi", "khóa", "banned", "chưa", "đăng nhập", "đăng xuất", "sai tài khoản"]
    .some((term) => value.includes(term));
}

function statusClass(account) {
  const value = normalizedStatus(account);
  if (["lỗi", "khóa", "banned", "sai tài khoản"].some((term) => value.includes(term))) {
    return " is-error";
  }
  if (["chưa", "đăng nhập", "đăng xuất"].some((term) => value.includes(term))) {
    return " is-warning";
  }
  return "";
}

function syncMetrics(state) {
  const summaryMatch = String(state.sync_status || "").match(
    /(\d+)\s+thành công,\s*(\d+)\s+cần đăng nhập,\s*(\d+)\s+chưa liên kết,\s*(\d+)\s+lỗi tạm thời/i,
  );
  if (summaryMatch) {
    const summaryMetrics = {
      success: Number(summaryMatch[1]),
      login: Number(summaryMatch[2]),
      unlinked: Number(summaryMatch[3]),
      error: Number(summaryMatch[4]),
    };
    const summaryTotal = Object.values(summaryMetrics)
      .reduce((total, count) => total + count, 0);
    if (summaryTotal === state.accounts.length) return summaryMetrics;
  }

  return state.accounts.reduce((metrics, account) => {
    const status = normalizedStatus(account);
    if (status.includes("chưa liên kết")) {
      return { ...metrics, unlinked: metrics.unlinked + 1 };
    }
    if (status.includes("đăng nhập") || status.includes("đăng xuất")) {
      return { ...metrics, login: metrics.login + 1 };
    }
    if (["lỗi", "khóa", "banned", "sai tài khoản", "không thể"]
      .some((term) => status.includes(term))) {
      return { ...metrics, error: metrics.error + 1 };
    }
    if (needsAttention(account)) {
      return { ...metrics, error: metrics.error + 1 };
    }
    return { ...metrics, success: metrics.success + 1 };
  }, { success: 0, login: 0, unlinked: 0, error: 0 });
}

function setSyncMetric(node, count) {
  node.textContent = String(count);
  node.closest(".sync-item").classList.toggle("is-active", count > 0);
}

function parsedQuotaPercent(value) {
  const match = String(value || "").match(/-?\d+(?:[.,]\d+)?/);
  if (!match) return null;
  return Math.max(0, Math.min(100, Number(match[0].replace(",", "."))));
}

function quotaPercent(value) {
  return parsedQuotaPercent(value) ?? 0;
}

function formatRefreshInterval(seconds) {
  if (seconds >= 60 && seconds % 60 === 0) {
    return `${seconds / 60} phút`;
  }
  return `${seconds} giây`;
}

function metadataRow(label, value) {
  const row = element("div", "meta-row");
  row.append(element("dt", "", label), element("dd", "", value || "—"));
  return row;
}

function createAccountCard(account) {
  const card = element("article", "account-card");
  const header = element("div", "card-header");
  const identity = element("div", "identity");
  identity.append(element("h3", "email", account.email));
  identity.append(element("p", "plan", account.plan_type || "Chưa xác định gói"));

  const pill = element(
    "span",
    `status-pill${statusClass(account)}`,
    account.account_state || "Chưa xác định",
  );
  header.append(identity, pill);

  const body = element("div", "card-body");
  const primaryData = element("div", "primary-data");

  const otpBlock = element("section", "otp-block");
  const otpHeading = element("div", "otp-heading");
  otpHeading.append(
    element("span", "data-label", "Mã OTP"),
    element("span", "otp-timer", `Còn ${account.otp_remaining_seconds} giây`),
  );
  const otpCode = actionButton(account.otp, "copy-otp", account.id, {
    className: "otp-code",
    field: "display",
    ariaLabel: `Sao chép mã OTP ${account.otp} của ${account.email}`,
  });
  otpCode.title = "Bấm để sao chép OTP";
  otpBlock.append(
    otpHeading,
    otpCode,
    createProgress(
      "otp-progress",
      account.otp_remaining_seconds,
      30,
      `OTP còn hiệu lực ${account.otp_remaining_seconds} giây`,
    ),
  );

  const quotaBlock = element("section", "quota-block");
  const quotaHeading = element("div", "quota-heading");
  quotaHeading.append(
    element("span", "data-label", "Quota còn lại"),
    element("span", "quota-cycle", account.quota_cycle || "Chưa có chu kỳ"),
  );
  const quotaValue = account.quota_remaining || "—";
  quotaBlock.append(
    quotaHeading,
    element("strong", "quota-value", quotaValue),
    createProgress(
      "quota-progress",
      quotaPercent(account.quota_remaining),
      100,
      `Quota còn lại ${quotaValue}`,
    ),
  );
  primaryData.append(otpBlock, quotaBlock);

  const metadata = element("dl", "meta-list");
  metadata.append(
    metadataRow("Đồng bộ", account.sync_status),
    metadataRow("Reset quota", account.quota_reset_at),
    metadataRow("Lần cuối", account.last_sync),
  );

  const actions = element("div", "card-actions");
  actions.append(
    actionButton("Sao chép email", "copy-email", account.id, {
      className: "button button-primary",
      ariaLabel: `Sao chép email ${account.email}`,
    }),
    actionButton("Sao chép mật khẩu", "copy-sensitive", account.id, {
      field: "password",
      ariaLabel: `Sao chép mật khẩu của ${account.email}`,
    }),
  );

  const optionToggle = actionButton("Tùy chọn", "toggle-options", account.id, {
    className: "button button-secondary option-toggle",
    ariaLabel: `Mở tùy chọn của ${account.email}`,
  });
  const optionsId = `account-options-${account.id}`;
  optionToggle.setAttribute("aria-expanded", "false");
  optionToggle.setAttribute("aria-controls", optionsId);
  const optionActions = element("div", "option-actions");
  optionActions.id = optionsId;
  optionActions.hidden = true;
  optionActions.append(
    actionButton("Sao chép OTP", "copy-otp", account.id, {
      ariaLabel: `Sao chép OTP của ${account.email}`,
    }),
    actionButton("Đồng bộ", "refresh", account.id, {
      ariaLabel: `Đồng bộ ${account.email}`,
    }),
    actionButton("Sao chép secret", "copy-sensitive", account.id, {
      field: "secret",
      ariaLabel: `Sao chép secret của ${account.email}`,
    }),
    actionButton("Liên kết Codex", "login", account.id, {
      ariaLabel: `Liên kết Codex cho ${account.email}`,
    }),
  );
  const deleteButton = actionButton("Xóa tài khoản", "delete", account.id, {
    className: "button button-danger",
    ariaLabel: `Xóa tài khoản ${account.email}`,
  });
  optionActions.append(deleteButton);
  actions.append(optionToggle, optionActions);

  card.dataset.accountId = account.id;
  card.dataset.email = account.email;
  card.dataset.otp = account.otp;
  card.dataset.needsAttention = String(needsAttention(account));
  const accountQuotaPercent = parsedQuotaPercent(account.quota_remaining);
  card.dataset.quotaKnown = String(accountQuotaPercent !== null);
  card.dataset.quotaPercent = String(accountQuotaPercent ?? 0);
  body.append(primaryData, metadata, actions);
  card.append(header, body);
  return card;
}

function cardMatchesFilter(card, filter) {
  const quotaKnown = card.dataset.quotaKnown === "true";
  const quota = Number(card.dataset.quotaPercent);
  if (filter === "usable") {
    return card.dataset.needsAttention === "false" && quotaKnown && quota > 0;
  }
  if (filter === "attention") return card.dataset.needsAttention === "true";
  if (filter === "quota-available") return quotaKnown && quota > 0;
  if (filter === "quota-low") return quotaKnown && quota > 0 && quota <= 20;
  if (filter === "quota-empty") return quotaKnown && quota === 0;
  if (filter === "quota-unknown") return !quotaKnown;
  return true;
}

function applyAccountFilters() {
  const filter = ui.accountFilter.value;
  const cards = Array.from(ui.accountGrid.querySelectorAll(".account-card"));
  let visibleCount = 0;

  cards.forEach((card) => {
    const visible = cardMatchesFilter(card, filter);
    card.hidden = !visible;
    if (visible) visibleCount += 1;
  });

  const totalCount = currentState.accounts.length;
  ui.visibleAccountCount.textContent = `${visibleCount} / ${totalCount}`;
  ui.emptyState.classList.toggle("is-hidden", visibleCount > 0);

  const emptyTitle = ui.emptyState.querySelector("h3");
  const emptyText = ui.emptyState.querySelector("p");
  const emptyAction = ui.emptyState.querySelector("[data-open-import]");
  if (totalCount === 0) {
    emptyTitle.textContent = "Chưa có tài khoản";
    emptyText.textContent = "Thêm tài khoản đầu tiên để bắt đầu lấy OTP và theo dõi quota.";
    emptyAction.hidden = false;
  } else if (visibleCount === 0) {
    emptyTitle.textContent = "Không tìm thấy tài khoản";
    emptyText.textContent = "Thử chọn một bộ lọc khác.";
    emptyAction.hidden = true;
  }
}

function captureCardInteraction() {
  const cards = Array.from(ui.accountGrid.querySelectorAll(".account-card"));
  const openAccountIds = new Set(
    cards
      .filter((card) => (
        card.querySelector(".option-toggle").getAttribute("aria-expanded") === "true"
      ))
      .map((card) => card.dataset.accountId),
  );
  const activeElement = document.activeElement;
  const activeCard = activeElement.closest?.(".account-card");
  if (!activeCard) return { openAccountIds, focusTarget: null };

  if (activeElement.matches("button[data-action]")) {
    return {
      openAccountIds,
      focusTarget: {
        accountId: activeCard.dataset.accountId,
        kind: "action",
        action: activeElement.dataset.action,
        field: activeElement.dataset.field || "",
      },
    };
  }

  return { openAccountIds, focusTarget: null };
}

function restoreCardInteraction(interaction) {
  const cards = Array.from(ui.accountGrid.querySelectorAll(".account-card"));
  cards.forEach((card) => {
    if (!card.hidden && interaction.openAccountIds.has(card.dataset.accountId)) {
      const optionToggle = card.querySelector(".option-toggle");
      optionToggle.setAttribute("aria-expanded", "true");
      optionToggle.setAttribute(
        "aria-label",
        `Đóng tùy chọn của ${card.dataset.email}`,
      );
      card.querySelector(".option-actions").hidden = false;
    }
  });

  const targetState = interaction.focusTarget;
  if (!targetState) return;
  const targetCard = cards.find(
    (card) => card.dataset.accountId === targetState.accountId,
  );
  if (!targetCard || targetCard.hidden) return;

  const targetButton = Array.from(
    targetCard.querySelectorAll("button[data-action]"),
  ).find((node) => (
    node.dataset.action === targetState.action
    && (node.dataset.field || "") === targetState.field
  ));
  targetButton?.focus();
}

function replaceAccountCards(accounts) {
  const interaction = captureCardInteraction();
  ui.accountGrid.replaceChildren(...accounts.map(createAccountCard));
  return interaction;
}

function renderState(state) {
  currentState = state;
  let cardInteraction = null;
  const metrics = syncMetrics(state);
  ui.accountCount.textContent = String(state.accounts.length);
  ui.syncStatus.textContent = state.sync_status;
  ui.syncSuccessRatio.textContent = `${metrics.success} / ${state.accounts.length}`;
  setSyncMetric(ui.syncSuccessCount, metrics.success);
  setSyncMetric(ui.syncLoginCount, metrics.login);
  setSyncMetric(ui.syncUnlinkedCount, metrics.unlinked);
  setSyncMetric(ui.syncErrorCount, metrics.error);
  ui.refreshInterval.textContent = formatRefreshInterval(
    state.refresh_interval_seconds,
  );

  const nextSignature = JSON.stringify({
    ...state,
    accounts: state.accounts.map(
      ({ otp: _otp, otp_remaining_seconds: _remaining, ...account }) => account,
    ),
  });

  if (nextSignature === renderSignature) {
    state.accounts.forEach((account) => {
      const card = ui.accountGrid.querySelector(`[data-account-id="${account.id}"]`);
      if (!card) return;
      card.dataset.otp = account.otp;
      const otpCode = card.querySelector(".otp-code");
      otpCode.textContent = account.otp;
      otpCode.setAttribute(
        "aria-label",
        `Sao chép mã OTP ${account.otp} của ${account.email}`,
      );
      card.querySelector(".otp-timer").textContent =
        `Còn ${account.otp_remaining_seconds} giây`;
      const otpProgress = card.querySelector(".otp-progress");
      otpProgress.value = account.otp_remaining_seconds;
      otpProgress.setAttribute(
        "aria-label",
        `OTP còn hiệu lực ${account.otp_remaining_seconds} giây`,
      );
    });
  } else {
    cardInteraction = replaceAccountCards(state.accounts);
    renderSignature = nextSignature;
  }

  applyAccountFilters();
  if (cardInteraction) {
    restoreCardInteraction(cardInteraction);
  }
  const updatedAt = new Date().toLocaleTimeString("vi-VN");
  ui.lastUpdated.textContent = updatedAt;
  ui.lastUpdated.setAttribute("aria-label", `Cập nhật lúc ${updatedAt}`);
  ui.connection.textContent = "Đang hoạt động";
  ui.connection.className = "connection is-online";
}

function showToast(message, isError = false) {
  window.clearTimeout(toastTimer);
  ui.toast.textContent = message;
  if (isError) {
    ui.toast.setAttribute("role", "alert");
    ui.toast.setAttribute("aria-live", "assertive");
  } else {
    ui.toast.setAttribute("role", "status");
    ui.toast.setAttribute("aria-live", "polite");
  }
  ui.toast.className = `toast is-visible${isError ? " is-error" : ""}`;
  toastTimer = window.setTimeout(() => {
    ui.toast.className = "toast";
  }, 3200);
}

async function api(path, options = {}) {
  const method = options.method || "GET";
  const headers = new Headers(options.headers || {});
  if (accessToken) headers.set("Authorization", `Bearer ${accessToken}`);
  if (method !== "GET" && method !== "HEAD") {
    headers.set("X-CSRF-Token", csrfToken);
  }
  if (options.body) headers.set("Content-Type", "application/json");

  const response = await fetch(path, { ...options, method, headers });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(payload.detail || `Yêu cầu thất bại (${response.status})`);
  }
  return payload;
}

async function bootstrap() {
  try {
    const payload = await api("/api/bootstrap");
    csrfToken = payload.csrf_token;
    renderState(payload.state);
  } catch (error) {
    setOffline(error);
  }
}

async function pollState() {
  if (pollInProgress) return;
  pollInProgress = true;
  try {
    renderState(await api("/api/state"));
  } catch (error) {
    setOffline(error);
  } finally {
    pollInProgress = false;
  }
}

function setOffline(error) {
  ui.connection.textContent = "Mất kết nối";
  ui.connection.className = "connection is-offline";
  ui.lastUpdated.textContent = `Không thể cập nhật: ${error.message}`;
}

async function copyText(value, label) {
  await navigator.clipboard.writeText(value);
  showToast(`Đã sao chép ${label}.`);
}

async function handleCardAction(event) {
  const actionButtonNode = event.target.closest("button[data-action]");
  if (!actionButtonNode) return;

  const card = actionButtonNode.closest(".account-card");
  const accountId = actionButtonNode.dataset.accountId;
  const action = actionButtonNode.dataset.action;
  if (action === "toggle-options") {
    const optionActions = card.querySelector(".option-actions");
    const expanded = actionButtonNode.getAttribute("aria-expanded") === "true";
    actionButtonNode.setAttribute("aria-expanded", String(!expanded));
    actionButtonNode.setAttribute(
      "aria-label",
      `${expanded ? "Mở" : "Đóng"} tùy chọn của ${card.dataset.email}`,
    );
    optionActions.hidden = expanded;
    return;
  }
  actionButtonNode.disabled = true;

  try {
    if (action === "copy-email") {
      await copyText(card.dataset.email, "email");
    } else if (action === "copy-otp") {
      await copyText(card.dataset.otp, "OTP");
    } else if (action === "copy-sensitive") {
      const field = actionButtonNode.dataset.field;
      const payload = await api(`/api/accounts/${accountId}/sensitive`, {
        method: "POST",
        body: JSON.stringify({ field }),
      });
      await copyText(payload.value, field === "password" ? "mật khẩu" : "secret");
    } else if (action === "refresh") {
      await api("/api/codex/refresh", {
        method: "POST",
        body: JSON.stringify({ account_id: accountId }),
      });
      showToast("Đã yêu cầu đồng bộ tài khoản.");
      await pollState();
    } else if (action === "login") {
      await api(`/api/codex/${accountId}/login`, { method: "POST" });
      showToast("Đã mở cửa sổ đăng nhập Codex.");
      await pollState();
    } else if (action === "delete") {
      const confirmed = window.confirm(
        `Xóa ${card.querySelector(".email").textContent} khỏi danh sách? Hồ sơ Codex vẫn được giữ lại.`,
      );
      if (!confirmed) return;
      await api(`/api/accounts/${accountId}`, { method: "DELETE" });
      showToast("Đã xóa tài khoản khỏi danh sách.");
      await pollState();
    }
  } catch (error) {
    showToast(error.message, true);
  } finally {
    actionButtonNode.disabled = false;
  }
}

function openImportDialog() {
  ui.importResult.textContent = "";
  ui.importResult.className = "import-result";
  ui.accountDialog.showModal();
  ui.accountLines.focus();
}

function closeImportDialog() {
  ui.accountDialog.close();
  ui.openImport.focus();
}

async function importAccounts() {
  const lines = ui.accountLines.value.trim();
  if (!lines) {
    ui.importResult.textContent = "Hãy nhập ít nhất một tài khoản.";
    ui.importResult.className = "import-result is-error";
    return;
  }

  ui.importAccounts.disabled = true;
  ui.importAccounts.textContent = "Đang lưu...";
  try {
    const result = await api("/api/accounts/import", {
      method: "POST",
      body: JSON.stringify({ lines }),
    });
    const summary = `Tổng ${result.total}; thêm ${result.added}; cập nhật ${result.updated}; trùng ${result.duplicates}.`;
    ui.importResult.textContent = result.errors.length
      ? `${summary} Lỗi: ${result.errors.join(" ")}`
      : summary;
    ui.importResult.className = result.errors.length
      ? "import-result is-error"
      : "import-result";

    await pollState();
    if (!result.errors.length) {
      ui.accountLines.value = "";
      ui.accountDialog.close();
      showToast(summary);
    }
  } catch (error) {
    ui.importResult.textContent = error.message;
    ui.importResult.className = "import-result is-error";
  } finally {
    ui.importAccounts.disabled = false;
    ui.importAccounts.textContent = "Lưu tài khoản";
  }
}

async function refreshAllAccounts() {
  ui.refreshAll.disabled = true;
  ui.refreshAll.textContent = "Đang đồng bộ...";
  try {
    const result = await api("/api/codex/refresh", {
      method: "POST",
      body: JSON.stringify({ account_id: null }),
    });
    showToast(result.accepted ? "Đã bắt đầu đồng bộ." : "Một lượt đồng bộ đang chạy.");
    await pollState();
  } catch (error) {
    showToast(error.message, true);
  } finally {
    ui.refreshAll.disabled = false;
    ui.refreshAll.textContent = "Đồng bộ tất cả";
  }
}

applyTheme(document.documentElement.dataset.theme, { persist: false });
ui.themeToggle.addEventListener("click", toggleTheme);
ui.openImport.addEventListener("click", openImportDialog);
document.querySelectorAll("[data-open-import]").forEach((node) => {
  node.addEventListener("click", openImportDialog);
});
ui.closeImport.addEventListener("click", closeImportDialog);
ui.cancelImport.addEventListener("click", closeImportDialog);
ui.importAccounts.addEventListener("click", importAccounts);
ui.refreshAll.addEventListener("click", refreshAllAccounts);
ui.accountGrid.addEventListener("click", handleCardAction);
ui.accountFilter.addEventListener("change", applyAccountFilters);

if (accessToken) {
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}

bootstrap();
window.setInterval(pollState, 1000);
