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
  timeSyncStatus: document.querySelector("#time-sync-status"),
  lastUpdated: document.querySelector("#last-updated"),
  accountFilter: document.querySelector("#account-filter"),
  shutdownApplication: document.querySelector("#shutdown-application"),
  accountDialog: document.querySelector("#account-dialog"),
  openImport: document.querySelector("#open-import"),
  closeImport: document.querySelector("#close-import"),
  cancelImport: document.querySelector("#cancel-import"),
  accountLines: document.querySelector("#account-lines"),
  importAccounts: document.querySelector("#import-accounts"),
  importResult: document.querySelector("#import-result"),
  accountGrid: document.querySelector("#account-grid"),
  emptyState: document.querySelector("#empty-state"),
  workspaceTabs: Array.from(document.querySelectorAll(".workspace-tab")),
  accountPanel: document.querySelector("#accounts-panel"),
  usagePanel: document.querySelector("#usage-panel"),
  tokenAccountSelect: document.querySelector("#token-account-select"),
  tokenDataStatus: document.querySelector("#token-data-status"),
  tokenUpdatedAt: document.querySelector("#token-updated-at"),
  selectedAccountSummary: document.querySelector("#selected-account-summary"),
  selectedAccountEmail: document.querySelector("#selected-account-email"),
  selectedAccountPlan: document.querySelector("#selected-account-plan"),
  tokenKpis: document.querySelector("#token-kpis"),
  tokenLifetime: document.querySelector("#token-lifetime"),
  tokenPeak: document.querySelector("#token-peak"),
  tokenLongestTask: document.querySelector("#token-longest-task"),
  tokenCurrentStreak: document.querySelector("#token-current-streak"),
  tokenLongestStreak: document.querySelector("#token-longest-streak"),
  tokenRangeButtons: Array.from(document.querySelectorAll("[data-token-range]")),
  tokenHeatmapTitle: document.querySelector("#token-heatmap-title"),
  tokenHeatmap: document.querySelector("#token-heatmap"),
  heatmapTooltip: document.querySelector("#heatmap-tooltip"),
  tokenUsageEmpty: document.querySelector("#token-usage-empty"),
  singleQuotaCard: document.querySelector("#single-quota-card"),
  singleQuotaRemaining: document.querySelector("#single-quota-remaining"),
  singleQuotaCycle: document.querySelector("#single-quota-cycle"),
  singleQuotaReset: document.querySelector("#single-quota-reset"),
  singleQuotaStatus: document.querySelector("#single-quota-status"),
  allAccountStatistics: document.querySelector("#all-account-statistics"),
  usageAverageRemaining: document.querySelector("#usage-average-remaining"),
  usageAverageProgress: document.querySelector("#usage-average-progress"),
  usageAverageProgressFill: document.querySelector("#usage-average-progress-fill"),
  usageKnownCount: document.querySelector("#usage-known-count"),
  usageUnknownCount: document.querySelector("#usage-unknown-count"),
  usageStaleCount: document.querySelector("#usage-stale-count"),
  usageAttentionCount: document.querySelector("#usage-attention-count"),
  usageUsableCount: document.querySelector("#usage-usable-count"),
  usageLowCount: document.querySelector("#usage-low-count"),
  usageExhaustedCount: document.querySelector("#usage-exhausted-count"),
  usageSnapshotTime: document.querySelector("#usage-snapshot-time"),
  usageDisclaimer: document.querySelector("#usage-disclaimer"),
  usageAccountRows: document.querySelector("#usage-account-rows"),
  usageEmpty: document.querySelector("#usage-empty"),
  toast: document.querySelector("#toast"),
};

const themeStorageKey = "otp-codex-theme";
const tokenStorageKey = "otp-codex-access-token";
const expectedApiSchemaVersion = 6;
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
let accountCheckRequestId = 0;
let accountCanBeAdded = false;
let pollTimer = 0;
let applicationStopping = false;
let backendCompatible = false;
let tokenUsageData = null;
let tokenUsageFetchedAt = 0;
let tokenFetchInProgress = false;
let selectedTokenRange = "daily";
let quotaUsageData = null;
let tokenRefreshPending = false;

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
  ui.themeColor.content = isDark ? "#0b1020" : "#e1e6ed";

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
  if (options.title) node.title = options.title;
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

function renderTimeSyncStatus(timeSync) {
  const status = timeSync || {};
  const offset = Number(status.offset_seconds);
  if (status.status === "synced" && Number.isFinite(offset)) {
    const roundedOffset = Math.round(offset);
    const sign = roundedOffset > 0 ? "+" : "";
    ui.timeSyncStatus.textContent = `Giờ OTP đã chuẩn · bù ${sign}${roundedOffset} giây`;
    return;
  }
  if (status.status === "degraded") {
    ui.timeSyncStatus.textContent = status.last_synced_at
      ? "Đang dùng mốc giờ chuẩn gần nhất"
      : "Chưa lấy được giờ chuẩn · OTP có thể lệch";
    return;
  }
  ui.timeSyncStatus.textContent = "Đang lấy giờ chuẩn cho OTP";
}

function metadataRow(label, value) {
  const row = element("div", "meta-row");
  row.append(element("dt", "", label), element("dd", "", value || "—"));
  return row;
}

function createAccountCard(account) {
  const recommended = account.id === currentState.recommendation?.account_id;
  const card = element("article", `account-card${recommended ? " is-recommended" : ""}`);
  const header = element("div", "card-header");
  const identity = element("div", "identity");
  identity.append(element("h3", "email", account.email));
  identity.append(element("p", "plan", account.plan_type || "Chưa xác định gói"));
  if (recommended) {
    identity.append(element("span", "recommendation-badge", "Đề xuất sử dụng"));
  }

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
  const otpAvailable = Boolean(account.otp);
  const otpRemaining = otpAvailable ? account.otp_remaining_seconds : 0;
  otpHeading.append(
    element("span", "data-label", "Mã OTP"),
    element(
      "span",
      "otp-timer",
      otpAvailable ? `Còn ${otpRemaining} giây` : "Chờ đồng bộ giờ chuẩn",
    ),
  );
  const otpCode = actionButton(
    account.otp || "OTP chưa sẵn sàng",
    "copy-otp",
    account.id,
    {
      className: "otp-code",
      field: "display",
      ariaLabel: otpAvailable
        ? `Sao chép mã OTP ${account.otp} của ${account.email}`
        : `OTP của ${account.email} chưa sẵn sàng`,
    },
  );
  otpCode.disabled = !otpAvailable;
  otpCode.title = otpAvailable
    ? "Bấm để sao chép OTP"
    : "Chưa lấy được giờ chuẩn nên OTP tạm khóa";
  otpBlock.append(
    otpHeading,
    otpCode,
    createProgress(
      "otp-progress",
      otpRemaining,
      30,
      otpAvailable
        ? `OTP còn hiệu lực ${otpRemaining} giây`
        : "OTP đang chờ đồng bộ giờ chuẩn",
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
  const copyOtpOption = actionButton("Sao chép OTP", "copy-otp", account.id, {
    ariaLabel: `Sao chép OTP của ${account.email}`,
  });
  copyOtpOption.disabled = !otpAvailable;
  optionActions.append(
    copyOtpOption,
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
    actionButton("Ngắt liên kết", "unlink", account.id, {
      ariaLabel: `Ngắt liên kết Codex của ${account.email}`,
      title: "Giữ tài khoản trong danh sách và lưu trữ profile đăng nhập hiện tại.",
    }),
    actionButton("Đặt lại profile", "reset-profile", account.id, {
      ariaLabel: `Đặt lại profile Codex của ${account.email}`,
      title: "Lưu trữ profile hiện tại và tạo profile trống để liên kết lại.",
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
  card.dataset.otp = account.otp || "";
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

function formatUsagePercent(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number) ? `${number.toLocaleString("vi-VN")}%` : "—";
}

function formatGeneratedTime(value) {
  if (!value) return "Đang tổng hợp dữ liệu";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return `Tổng hợp lúc ${value}`;
  return `Tổng hợp lúc ${date.toLocaleString("vi-VN")}`;
}

function formatTokenCount(value) {
  if (value === null || value === undefined || value === "") return "—";
  const number = Number(value);
  return Number.isFinite(number) ? Math.round(number).toLocaleString("vi-VN") : "—";
}

function formatIsoDate(value, options = {}) {
  const parsed = new Date(`${value}T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return value || "—";
  return parsed.toLocaleDateString("vi-VN", options);
}

function localIsoDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addDays(date, days) {
  const result = new Date(date);
  result.setDate(result.getDate() + days);
  return result;
}

function mondayOf(date) {
  const offset = (date.getDay() + 6) % 7;
  return addDays(date, -offset);
}

function formatDuration(value) {
  if (value === null || value === undefined || value === "") return "—";
  const seconds = Math.round(Number(value));
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  if (seconds < 60) return `${seconds} giây`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours === 0) return `${minutes} phút`;
  return minutes > 0 ? `${hours} giờ ${minutes} phút` : `${hours} giờ`;
}

function formatDays(value) {
  if (value === null || value === undefined || value === "") return "—";
  const days = Math.round(Number(value));
  return Number.isFinite(days) && days >= 0 ? `${days} ngày` : "—";
}

function selectedTokenAccount() {
  if (ui.tokenAccountSelect.value === "all") return null;
  return (tokenUsageData?.accounts || []).find(
    (account) => account.account_id === ui.tokenAccountSelect.value,
  ) || null;
}

function selectedQuotaAccount() {
  return (quotaUsageData?.accounts || []).find(
    (account) => account.account_id === ui.tokenAccountSelect.value,
  ) || null;
}

function selectedDailyBuckets() {
  if (!tokenUsageData) return null;
  if (ui.tokenAccountSelect.value === "all") {
    return tokenUsageData.aggregate?.daily_buckets ?? null;
  }
  return selectedTokenAccount()?.daily_buckets ?? null;
}

function heatmapRange() {
  const end = new Date();
  end.setHours(0, 0, 0, 0);
  const start = new Date(end);
  start.setFullYear(start.getFullYear() - 1);
  start.setDate(start.getDate() + 1);
  const gridStart = mondayOf(start);
  const gridEnd = addDays(mondayOf(end), 6);
  return {
    start,
    end,
    gridStart,
    weekCount: Math.round((gridEnd - gridStart) / 604800000) + 1,
  };
}

function heatmapLevel(tokens, maximum) {
  if (tokens <= 0) return 0;
  return Math.max(1, Math.min(4, Math.ceil((tokens / Math.max(1, maximum)) * 4)));
}

function heatmapCell(tokens, maximum, tooltip, className = "") {
  const cell = element(
    "button",
    `heatmap-cell level-${heatmapLevel(tokens, maximum)} ${className}`.trim(),
  );
  cell.type = "button";
  cell.dataset.tooltip = tooltip;
  cell.setAttribute("aria-label", tooltip);
  cell.setAttribute("aria-describedby", "heatmap-tooltip");
  return cell;
}

function showHeatmapTooltip(cell) {
  const tooltip = cell?.dataset.tooltip;
  if (!tooltip) return;
  ui.heatmapTooltip.textContent = tooltip;
  ui.heatmapTooltip.hidden = false;
  const cellRect = cell.getBoundingClientRect();
  const tooltipRect = ui.heatmapTooltip.getBoundingClientRect();
  const left = Math.max(
    8,
    Math.min(
      window.innerWidth - tooltipRect.width - 8,
      cellRect.left + cellRect.width / 2 - tooltipRect.width / 2,
    ),
  );
  const preferredTop = cellRect.top - tooltipRect.height - 8;
  const top = preferredTop >= 8 ? preferredTop : cellRect.bottom + 8;
  ui.heatmapTooltip.style.left = `${left}px`;
  ui.heatmapTooltip.style.top = `${top}px`;
}

function hideHeatmapTooltip() {
  ui.heatmapTooltip.hidden = true;
}

function renderHeatmap(buckets) {
  ui.tokenHeatmap.replaceChildren();
  if (buckets === null) {
    ui.tokenHeatmap.append(element(
      "p",
      "heatmap-unavailable",
      "Dữ liệu heatmap chưa khả dụng cho phạm vi này.",
    ));
    return;
  }

  const range = heatmapRange();
  const rangeStartKey = localIsoDate(range.start);
  const rangeEndKey = localIsoDate(range.end);
  const tokenByDate = new Map();
  (Array.isArray(buckets) ? buckets : []).forEach((bucket) => {
    const tokens = Number(bucket.tokens);
    if (
      typeof bucket.start_date === "string"
      && bucket.start_date >= rangeStartKey
      && bucket.start_date <= rangeEndKey
      && Number.isFinite(tokens)
      && tokens >= 0
    ) {
      tokenByDate.set(
        bucket.start_date,
        (tokenByDate.get(bucket.start_date) || 0) + Math.round(tokens),
      );
    }
  });

  const weeks = Array.from({ length: range.weekCount }, (_, weekIndex) => {
    const start = addDays(range.gridStart, weekIndex * 7);
    const days = Array.from({ length: 7 }, (_, dayIndex) => addDays(start, dayIndex));
    return {
      start,
      end: days[6],
      days,
      tokens: days.reduce((sum, date) => sum + (tokenByDate.get(localIsoDate(date)) || 0), 0),
    };
  }).filter((week) => week.start <= range.end && week.end >= range.start);
  let cumulative = 0;
  weeks.forEach((week) => {
    cumulative += week.tokens;
    week.cumulative = cumulative;
  });

  const months = element("div", "heatmap-months");
  months.style.gridTemplateColumns = `repeat(${weeks.length}, var(--heatmap-cell-size))`;
  const monthGroups = [];
  weeks.forEach((week, index) => {
    const key = `${week.start.getFullYear()}-${week.start.getMonth()}`;
    const current = monthGroups[monthGroups.length - 1];
    if (current?.key === key) {
      current.end = index + 1;
      return;
    }
    monthGroups.push({
      key,
      start: index,
      end: index + 1,
      date: week.start,
    });
  });
  monthGroups.forEach((group) => {
    const month = group.date.getMonth() + 1;
    const label = element("span", "heatmap-month", `T${month}`);
    label.style.gridColumn = `${group.start + 1} / ${group.end + 1}`;
    months.append(label);
  });

  const grid = element("div", `heatmap-grid is-${selectedTokenRange}`);
  grid.style.gridTemplateColumns = `repeat(${weeks.length}, var(--heatmap-cell-size))`;
  const values = selectedTokenRange === "daily"
    ? weeks.flatMap((week) => week.days.map((date) => tokenByDate.get(localIsoDate(date)) || 0))
    : weeks.map((week) => (
      selectedTokenRange === "weekly" ? week.tokens : week.cumulative
    ));
  const maximum = Math.max(1, ...values);

  if (selectedTokenRange === "daily") {
    weeks.forEach((week, weekIndex) => {
      week.days.forEach((date, dayIndex) => {
        const dateKey = localIsoDate(date);
        const inRange = date >= range.start && date <= range.end;
        if (!inRange) return;
        const tokens = tokenByDate.get(dateKey) || 0;
        const tooltip = `${formatTokenCount(tokens)} token · ${formatIsoDate(dateKey, {
          weekday: "short",
          day: "2-digit",
          month: "2-digit",
          year: "numeric",
        })}`;
        const cell = heatmapCell(tokens, maximum, tooltip);
        cell.style.gridColumn = String(weekIndex + 1);
        cell.style.gridRow = String(dayIndex + 1);
        grid.append(cell);
      });
    });
  } else {
    weeks.forEach((week, weekIndex) => {
      const tokens = selectedTokenRange === "weekly" ? week.tokens : week.cumulative;
      const visibleStart = week.start < range.start ? range.start : week.start;
      const visibleEnd = week.end > range.end ? range.end : week.end;
      const dateRange = `${formatIsoDate(localIsoDate(visibleStart), {
        day: "2-digit",
        month: "2-digit",
      })}–${formatIsoDate(localIsoDate(visibleEnd), {
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
      })}`;
      const prefix = selectedTokenRange === "cumulative" ? "Lũy kế đến tuần" : "Tuần";
      const tooltip = `${formatTokenCount(tokens)} token · ${prefix} ${dateRange}`;
      week.days.forEach((_, dayIndex) => {
        const cell = heatmapCell(tokens, maximum, tooltip);
        cell.style.gridColumn = String(weekIndex + 1);
        cell.style.gridRow = String(dayIndex + 1);
        grid.append(cell);
      });
    });
  }

  ui.tokenHeatmap.append(months, grid);
}

function renderSingleAccount(account, quotaAccount) {
  const isSingle = ui.tokenAccountSelect.value !== "all";
  ui.selectedAccountSummary.hidden = !isSingle;
  ui.tokenKpis.hidden = !isSingle;
  ui.singleQuotaCard.hidden = !isSingle;
  ui.allAccountStatistics.hidden = isSingle;
  if (!isSingle) return;

  ui.selectedAccountEmail.textContent = quotaAccount?.email || account?.email || "Tài khoản không xác định";
  ui.selectedAccountPlan.textContent = quotaAccount?.plan_type || "Chưa rõ gói";
  ui.selectedAccountPlan.className = "status-badge";
  ui.tokenLifetime.textContent = formatTokenCount(account?.lifetime);
  ui.tokenPeak.textContent = formatTokenCount(account?.peak_daily);
  ui.tokenLongestTask.textContent = formatDuration(account?.longest_running_turn_seconds);
  ui.tokenCurrentStreak.textContent = formatDays(account?.current_streak_days);
  ui.tokenLongestStreak.textContent = formatDays(account?.longest_streak_days);
  ui.singleQuotaRemaining.textContent = formatUsagePercent(quotaAccount?.quota_remaining_percent);
  ui.singleQuotaCycle.textContent = `Chu kỳ: ${quotaAccount?.quota_cycle || "—"}`;
  ui.singleQuotaReset.textContent = quotaAccount?.quota_reset_at || "—";
  if (quotaAccount) {
    const category = quotaCategory(quotaAccount);
    ui.singleQuotaStatus.replaceChildren(element(
      "span",
      `status-badge is-${category}`,
      quotaCategoryDetails[category].label,
    ));
  } else {
    ui.singleQuotaStatus.textContent = "—";
  }
}

function renderTokenUsage() {
  if (!tokenUsageData) return;
  const account = selectedTokenAccount();
  const quotaAccount = selectedQuotaAccount();
  const coverage = tokenUsageData.coverage || {};
  const total = Number(coverage.total_accounts ?? tokenUsageData.accounts?.length ?? 0);
  const fresh = Number(coverage.fresh_accounts || 0);
  const stale = Number(coverage.stale_accounts || 0);
  const unavailable = Number(coverage.unavailable_accounts || 0);
  const buckets = selectedDailyBuckets();
  const status = account?.status || (
    buckets === null ? "unavailable" : (stale > 0 ? "stale" : "fresh")
  );
  const statusLabels = { fresh: "Mới", stale: "Dữ liệu cũ", unavailable: "Không lấy được" };
  ui.tokenDataStatus.textContent = statusLabels[status] || "Không lấy được";
  ui.tokenDataStatus.className = `status-badge is-${status}`;
  ui.tokenUpdatedAt.textContent = ui.tokenAccountSelect.value === "all"
    ? `${formatGeneratedTime(tokenUsageData.generated_at)} · ${fresh} mới, ${stale} cũ, ${unavailable} chưa có`
    : formatGeneratedTime(account?.updated_at || tokenUsageData.generated_at);
  ui.tokenHeatmapTitle.textContent = {
    daily: "Token theo ngày",
    weekly: "Token theo tuần",
    cumulative: "Token lũy kế",
  }[selectedTokenRange];
  renderSingleAccount(account, quotaAccount);
  renderHeatmap(buckets);
  ui.tokenUsageEmpty.hidden = true;
}

function updateTokenAccountOptions() {
  const selected = ui.tokenAccountSelect.value || "all";
  const options = [element("option", "", "Tất cả tài khoản")];
  options[0].value = "all";
  const accountsById = new Map();
  (quotaUsageData?.accounts || []).forEach((account) => {
    accountsById.set(account.account_id, account.email);
  });
  (tokenUsageData?.accounts || []).forEach((account) => {
    if (!accountsById.has(account.account_id)) {
      accountsById.set(account.account_id, account.email);
    }
  });
  Array.from(accountsById.entries())
    .sort((left, right) => left[1].localeCompare(right[1]))
    .forEach(([accountId, email]) => {
      const option = element("option", "", email);
      option.value = accountId;
      options.push(option);
    });
  ui.tokenAccountSelect.replaceChildren(...options);
  ui.tokenAccountSelect.value = options.some((option) => option.value === selected)
    ? selected
    : "all";
}

async function fetchTokenUsage() {
  if (!backendCompatible || tokenFetchInProgress) return;
  tokenFetchInProgress = true;
  ui.tokenDataStatus.textContent = "Đang tải";
  ui.tokenDataStatus.className = "status-badge is-unavailable";
  try {
    tokenUsageData = await api("/api/usage/tokens");
    tokenUsageFetchedAt = Date.now();
    updateTokenAccountOptions();
    renderTokenUsage();
    if (quotaUsageData) renderQuotaRows();
  } catch (error) {
    ui.tokenDataStatus.textContent = "Không lấy được";
    ui.tokenDataStatus.className = "status-badge is-unavailable";
    ui.tokenUpdatedAt.textContent = error.message;
    if (!tokenUsageData) ui.tokenUsageEmpty.hidden = false;
  } finally {
    tokenFetchInProgress = false;
  }
}

function usageCell(value, className = "", label = "") {
  const cell = element("td", className, value === null || value === undefined ? "—" : String(value));
  if (label) cell.dataset.label = label;
  return cell;
}

function quotaCategory(account) {
  if (account.needs_attention) return "attention";
  const remaining = Number(account.quota_remaining_percent);
  if (account.quota_remaining_percent !== null && Number.isFinite(remaining)) {
    if (remaining <= 0) return "exhausted";
    if (remaining <= 20) return "low";
  }
  if (account.quota_is_stale) return "stale";
  if (account.quota_remaining_percent === null) return "unavailable";
  return account.is_usable ? "usable" : "unavailable";
}

const quotaCategoryDetails = {
  attention: { label: "Cần xử lý", rank: 0 },
  exhausted: { label: "Hết quota", rank: 1 },
  low: { label: "Quota thấp", rank: 2 },
  stale: { label: "Cần đồng bộ", rank: 3 },
  unavailable: { label: "Chưa có dữ liệu", rank: 4 },
  usable: { label: "Dùng được", rank: 5 },
};

function quotaProgressCell(account) {
  const cell = usageCell(null, "quota-cell", "Quota còn lại");
  const remaining = account.quota_remaining_percent;
  const value = Number(remaining);
  cell.textContent = "";
  cell.append(element("strong", "usage-number", formatUsagePercent(remaining)));
  if (remaining !== null && Number.isFinite(value)) {
    const progress = createProgress(
      "quota-progress",
      value,
      100,
      `Quota còn lại ${formatUsagePercent(value)} của ${account.email}`,
    );
    cell.append(progress);
  }
  return cell;
}

function renderQuotaRows() {
  const sourceRows = Array.isArray(quotaUsageData?.accounts) ? quotaUsageData.accounts : [];
  const rows = sourceRows
    .map((account) => ({ ...account, quota_category: quotaCategory(account) }))
    .sort((left, right) => (
      quotaCategoryDetails[left.quota_category].rank
      - quotaCategoryDetails[right.quota_category].rank
      || left.email.localeCompare(right.email)
    ));
  const tableRows = rows.map((account) => {
    const row = element("tr");
    const tokenAccount = (tokenUsageData?.accounts || []).find(
      (item) => item.account_id === account.account_id,
    );
    row.dataset.quotaCategory = account.quota_category;
    const statusCell = usageCell(null, "", "Trạng thái");
    statusCell.textContent = "";
    statusCell.append(element(
      "span",
      `status-badge is-${account.quota_category}`,
      quotaCategoryDetails[account.quota_category].label,
    ));
    row.append(
      usageCell(account.email, "usage-account-email", "Tài khoản"),
      usageCell(account.plan_type, "", "Gói"),
      usageCell(formatTokenCount(tokenAccount?.lifetime), "usage-number", "Lifetime"),
      usageCell(formatTokenCount(tokenAccount?.peak_daily), "usage-number", "Peak/ngày"),
      usageCell(formatDuration(tokenAccount?.longest_running_turn_seconds), "", "Longest task"),
      usageCell(formatDays(tokenAccount?.current_streak_days), "", "Current streak"),
      usageCell(formatDays(tokenAccount?.longest_streak_days), "", "Longest streak"),
      quotaProgressCell(account),
      statusCell,
      usageCell(account.quota_reset_at, "", "Reset quota"),
      usageCell(account.last_sync, "", "Đồng bộ cuối"),
    );
    return row;
  });
  ui.usageAccountRows.replaceChildren(...tableRows);
  ui.usageEmpty.hidden = rows.length > 0;
  ui.usageAccountRows.closest("table").hidden = rows.length === 0;
}

function renderUsageStatistics(usageStatistics) {
  const statistics = usageStatistics || {};
  quotaUsageData = statistics;
  const total = Number(statistics.total_accounts || 0);
  const known = Number(statistics.quota_known_accounts || 0);
  const rows = Array.isArray(statistics.accounts) ? statistics.accounts : [];
  const categoryCounts = Object.fromEntries(
    Object.keys(quotaCategoryDetails).map((key) => [key, 0]),
  );
  rows.forEach((account) => {
    categoryCounts[quotaCategory(account)] += 1;
  });
  ui.usageAverageRemaining.textContent = known > 0
    ? formatUsagePercent(statistics.average_remaining_percent)
    : "—";
  const averageRemaining = known > 0
    ? Math.max(0, Math.min(100, Number(statistics.average_remaining_percent) || 0))
    : 0;
  ui.usageAverageProgress.setAttribute("aria-valuenow", String(averageRemaining));
  ui.usageAverageProgressFill.style.width = `${averageRemaining}%`;
  ui.usageKnownCount.textContent = `${known} / ${total} có dữ liệu`;
  ui.usageUnknownCount.textContent = `${Number(statistics.quota_unknown_accounts || 0)} chưa có dữ liệu`;
  ui.usageStaleCount.textContent = `${Number(statistics.stale_quota_accounts || 0)} cần đồng bộ`;
  ui.usageAttentionCount.textContent = String(categoryCounts.attention);
  ui.usageUsableCount.textContent = String(categoryCounts.usable);
  ui.usageLowCount.textContent = String(categoryCounts.low);
  ui.usageExhaustedCount.textContent = String(categoryCounts.exhausted);
  ui.usageSnapshotTime.textContent = formatGeneratedTime(statistics.generated_at);
  ui.usageDisclaimer.textContent =
    "Quota là phần trăm cửa sổ giới hạn hiện tại và không quy đổi từ token. Tài khoản cần xử lý hoặc dữ liệu cũ không được tính vào bình quân.";
  updateTokenAccountOptions();
  renderQuotaRows();
  if (tokenUsageData) renderTokenUsage();
}

function activateTab(tab, tabs) {
  tabs.forEach((candidate) => {
    const selected = candidate === tab;
    candidate.setAttribute("aria-selected", String(selected));
    candidate.tabIndex = selected ? 0 : -1;
    candidate.classList.toggle("is-active", selected);
    const panel = document.querySelector(`#${candidate.getAttribute("aria-controls")}`);
    panel.hidden = !selected;
  });
  if (tab.id === "usage-tab" && Date.now() - tokenUsageFetchedAt >= 300000) {
    fetchTokenUsage();
  }
}

function handleTabKeydown(event, tabs) {
  let direction = 0;
  if (event.key === "ArrowRight") direction = 1;
  if (event.key === "ArrowLeft") direction = -1;
  if (direction === 0) return;
  event.preventDefault();
  const currentIndex = tabs.indexOf(event.currentTarget);
  const nextIndex = (currentIndex + direction + tabs.length) % tabs.length;
  activateTab(tabs[nextIndex], tabs);
  tabs[nextIndex].focus();
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
  renderTimeSyncStatus(state.time_sync);
  renderUsageStatistics(state.usage_statistics);
  if (
    tokenRefreshPending
    && !String(state.sync_status || "").startsWith("Đang đồng bộ")
  ) {
    tokenRefreshPending = false;
    fetchTokenUsage();
  }

  const { usage_statistics: _usageStatistics, ...stableState } = state;
  const nextSignature = JSON.stringify({
    ...stableState,
    accounts: state.accounts.map(
      ({ otp: _otp, otp_remaining_seconds: _remaining, ...account }) => account,
    ),
  });

  if (nextSignature === renderSignature) {
    state.accounts.forEach((account) => {
      const card = ui.accountGrid.querySelector(`[data-account-id="${account.id}"]`);
      if (!card) return;
      const otpAvailable = Boolean(account.otp);
      const otpRemaining = otpAvailable ? account.otp_remaining_seconds : 0;
      card.dataset.otp = account.otp || "";
      const otpCode = card.querySelector(".otp-code");
      otpCode.textContent = account.otp || "OTP chưa sẵn sàng";
      otpCode.disabled = !otpAvailable;
      otpCode.setAttribute(
        "aria-label",
        otpAvailable
          ? `Sao chép mã OTP ${account.otp} của ${account.email}`
          : `OTP của ${account.email} chưa sẵn sàng`,
      );
      card.querySelector(".otp-timer").textContent =
        otpAvailable ? `Còn ${otpRemaining} giây` : "Chờ đồng bộ giờ chuẩn";
      const otpProgress = card.querySelector(".otp-progress");
      otpProgress.value = otpRemaining;
      otpProgress.setAttribute(
        "aria-label",
        otpAvailable
          ? `OTP còn hiệu lực ${otpRemaining} giây`
          : "OTP đang chờ đồng bộ giờ chuẩn",
      );
      card.querySelector('.option-actions [data-action="copy-otp"]').disabled =
        !otpAvailable;
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
    const error = new Error(
      payload.detail || `Yêu cầu thất bại (${response.status})`,
    );
    error.status = response.status;
    throw error;
  }
  return payload;
}

async function bootstrap() {
  try {
    const payload = await api("/api/bootstrap");
    if (payload.api_schema_version !== expectedApiSchemaVersion) {
      backendCompatible = false;
      const versionError = new Error(
        "Dịch vụ nền đang dùng phiên bản cũ. Hãy đóng OTP Codex Local và mở lại.",
      );
      versionError.code = "BACKEND_VERSION_MISMATCH";
      throw versionError;
    }
    backendCompatible = true;
    csrfToken = payload.csrf_token;
    renderState(payload.state);
  } catch (error) {
    setOffline(error);
  }
}

async function pollState() {
  if (!backendCompatible || applicationStopping || pollInProgress) return;
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
  const versionMismatch = error.code === "BACKEND_VERSION_MISMATCH";
  ui.connection.textContent = versionMismatch
    ? "Cần khởi động lại"
    : "Mất kết nối";
  ui.connection.className = "connection is-offline";
  ui.lastUpdated.textContent = `Không thể cập nhật: ${error.message}`;
  if (versionMismatch) {
    ui.openImport.disabled = true;
    ui.refreshAll.disabled = true;
    ui.shutdownApplication.disabled = true;
  }
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
      const result = await api("/api/codex/refresh", {
        method: "POST",
        body: JSON.stringify({
          account_id: accountId,
          force_token_usage: true,
        }),
      });
      tokenRefreshPending = result.accepted;
      showToast("Đã yêu cầu đồng bộ tài khoản.");
      await pollState();
    } else if (action === "login") {
      await api(`/api/codex/${accountId}/login`, { method: "POST" });
      showToast("Đã mở cửa sổ đăng nhập Codex.");
      await pollState();
    } else if (action === "unlink") {
      const confirmed = window.confirm(
        `Ngắt liên kết Codex của ${card.dataset.email}? Profile hiện tại sẽ được chuyển vào vùng lưu trữ.`,
      );
      if (!confirmed) return;
      await api(`/api/codex/${accountId}/unlink`, { method: "POST" });
      showToast("Đã ngắt liên kết Codex.");
      await pollState();
    } else if (action === "reset-profile") {
      const confirmed = window.confirm(
        `Đặt lại profile Codex của ${card.dataset.email}? Bạn sẽ cần liên kết lại tài khoản.`,
      );
      if (!confirmed) return;
      await api(`/api/codex/${accountId}/reset-profile`, { method: "POST" });
      showToast("Đã đặt lại profile Codex.");
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
  resetAccountCheck();
  ui.accountDialog.showModal();
  ui.accountLines.focus();
}

function resetAccountCheck() {
  accountCheckRequestId += 1;
  accountCanBeAdded = false;
  ui.importResult.textContent = "";
  ui.importResult.className = "import-result";
  ui.importAccounts.disabled = true;
}

async function checkAccountInput() {
  const requestedLines = ui.accountLines.value.trim();
  const requestId = ++accountCheckRequestId;
  accountCanBeAdded = false;
  ui.importAccounts.disabled = true;
  if (!requestedLines) {
    ui.importResult.textContent = "";
    ui.importResult.className = "import-result";
    return;
  }
  ui.importResult.textContent = "Đang kiểm tra tài khoản...";
  ui.importResult.className = "import-result";
  try {
    const result = await api("/api/accounts/import/check", {
      method: "POST",
      body: JSON.stringify({ lines: requestedLines }),
    });
    if (
      requestId !== accountCheckRequestId
      || ui.accountLines.value.trim() !== requestedLines
    ) {
      return;
    }
    accountCanBeAdded = result.valid === true;
    ui.importResult.textContent = result.message;
    ui.importResult.className = result.valid
      ? "import-result"
      : "import-result is-error";
    ui.importAccounts.disabled = !accountCanBeAdded;
  } catch (error) {
    if (requestId !== accountCheckRequestId) return;
    ui.importResult.textContent = error.message;
    ui.importResult.className = "import-result is-error";
  }
}

function closeImportDialog() {
  resetAccountCheck();
  ui.accountLines.value = "";
  ui.accountDialog.close();
  ui.openImport.focus();
}

async function importAccounts() {
  if (!accountCanBeAdded) {
    ui.importResult.textContent = "Tài khoản chưa vượt qua kiểm tra trùng.";
    ui.importResult.className = "import-result is-error";
    return;
  }

  const requestedLines = ui.accountLines.value.trim();
  ui.importAccounts.disabled = true;
  ui.importAccounts.textContent = "Đang lưu...";
  try {
    const result = await api("/api/accounts/import", {
      method: "POST",
      body: JSON.stringify({ lines: requestedLines }),
    });
    const summary = `Đã thêm ${result.email}.`;
    await pollState();
    ui.accountLines.value = "";
    resetAccountCheck();
    ui.accountDialog.close();
    showToast(summary);
  } catch (error) {
    ui.importResult.textContent = error.message;
    ui.importResult.className = "import-result is-error";
    await checkAccountInput();
  } finally {
    ui.importAccounts.textContent = "Thêm tài khoản";
    ui.importAccounts.disabled = !accountCanBeAdded;
  }
}

async function shutdownApplication() {
  const confirmed = window.confirm(
    "Thoát ứng dụng OTP Codex? Trang này sẽ ngừng cập nhật sau khi ứng dụng tắt.",
  );
  if (!confirmed) return;
  ui.shutdownApplication.disabled = true;
  applicationStopping = true;
  window.clearInterval(pollTimer);
  ui.connection.textContent = "Ứng dụng đang tắt";
  ui.connection.className = "connection";
  try {
    await api("/api/application/shutdown", { method: "POST" });
    showToast("Ứng dụng đang tắt. Bạn có thể đóng trang này.");
  } catch (error) {
    if (!error.status) {
      showToast("Kết nối đã đóng sau khi gửi yêu cầu thoát.");
      return;
    }
    applicationStopping = false;
    pollTimer = window.setInterval(pollState, 1000);
    ui.connection.textContent = "Đang hoạt động";
    ui.connection.className = "connection is-online";
    ui.shutdownApplication.disabled = false;
    showToast(error.message, true);
  }
}

async function refreshAllAccounts() {
  ui.refreshAll.disabled = true;
  ui.refreshAll.textContent = "Đang đồng bộ...";
  try {
    const result = await api("/api/codex/refresh", {
      method: "POST",
      body: JSON.stringify({
        account_id: null,
        force_token_usage: true,
      }),
    });
    tokenRefreshPending = result.accepted;
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
ui.accountLines.addEventListener("input", checkAccountInput);
ui.importAccounts.addEventListener("click", importAccounts);
ui.refreshAll.addEventListener("click", refreshAllAccounts);
ui.shutdownApplication.addEventListener("click", shutdownApplication);
ui.accountGrid.addEventListener("click", handleCardAction);
ui.accountFilter.addEventListener("change", applyAccountFilters);
ui.tokenAccountSelect.addEventListener("change", () => {
  renderTokenUsage();
});
ui.tokenHeatmap.addEventListener("pointerover", (event) => {
  showHeatmapTooltip(event.target.closest(".heatmap-cell"));
});
ui.tokenHeatmap.addEventListener("pointerout", hideHeatmapTooltip);
ui.tokenHeatmap.addEventListener("focusin", (event) => {
  showHeatmapTooltip(event.target.closest(".heatmap-cell"));
});
ui.tokenHeatmap.addEventListener("focusout", hideHeatmapTooltip);
ui.tokenRangeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectedTokenRange = button.dataset.tokenRange;
    ui.tokenRangeButtons.forEach((candidate) => {
      const selected = candidate === button;
      candidate.classList.toggle("is-active", selected);
      candidate.setAttribute("aria-pressed", String(selected));
    });
    renderTokenUsage();
  });
});
ui.workspaceTabs.forEach((tab) => {
  tab.addEventListener("click", () => activateTab(tab, ui.workspaceTabs));
  tab.addEventListener("keydown", (event) => handleTabKeydown(event, ui.workspaceTabs));
});

if (accessToken) {
  window.history.replaceState(null, "", window.location.pathname + window.location.search);
}

bootstrap();
pollTimer = window.setInterval(pollState, 1000);
