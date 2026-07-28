<script setup lang="ts">
import {
  computed,
  nextTick,
  onMounted,
  ref,
  watch,
} from "vue";

import GlassButton from "@/components/glass/GlassButton.vue";
import GlassSegmentedControl from "@/components/glass/GlassSegmentedControl.vue";
import GlassSelectPopover from "@/components/glass/GlassSelectPopover.vue";
import { useSessionStore } from "@/stores/session.ts";
import { useUsageStore } from "@/stores/usage.ts";
import type {
  AccountUsageStatistics,
  TokenUsageAccount,
} from "@/types/api.ts";
import {
  buildHeatmapCells,
  buildHeatmapMonthLabels,
  heatmapLevel,
  resolveHeatmapEndDate,
  type HeatmapCell,
  type HeatmapMode,
} from "@/utils/heatmap.ts";

interface AccountTableRow {
  accountId: string;
  email: string;
  quota: AccountUsageStatistics | null;
  token: TokenUsageAccount | null;
}

interface HeatmapPointerTooltip {
  cell: HeatmapCell;
  placeLeft: boolean;
  x: number;
  y: number;
}

type QuotaCategory =
  | "attention"
  | "exhausted"
  | "low"
  | "stale"
  | "unavailable"
  | "usable";

const session = useSessionStore();
const usage = useUsageStore();
const activeCellStart = ref("");
const pointerTooltip = ref<HeatmapPointerTooltip | null>(null);

const heatmapModes: ReadonlyArray<{ value: HeatmapMode; label: string }> = [
  { value: "daily", label: "Ngày" },
  { value: "weekly", label: "Tuần" },
  { value: "cumulative", label: "Tích lũy" },
];
const accountScopeOptions = computed(() => [
  { value: "all", label: "Tất cả tài khoản" },
  ...usage.accountOptions.map((account) => ({
    value: account.accountId,
    label: account.email,
  })),
]);
const yesterdayLabel = computed(() => {
  const generatedDate = usage.data?.generated_at.slice(0, 10);
  const [year, month, day] = generatedDate?.split("-").map(Number) ?? [];
  const now = new Date();
  const date = year && month && day
    ? new Date(Date.UTC(year, month - 1, day))
    : new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
  date.setUTCDate(date.getUTCDate() - 1);
  return `Hôm qua · ${String(date.getUTCDate()).padStart(2, "0")}/${String(
    date.getUTCMonth() + 1,
  ).padStart(2, "0")}/${date.getUTCFullYear()}`;
});
const allTotalCards = computed(() => [
  { key: "today", label: yesterdayLabel.value },
  { key: "week", label: "Tuần này" },
  { key: "month", label: "Tháng này" },
  { key: "lifetime", label: "Lifetime" },
] as const);

const heatmapEndDate = computed(() => resolveHeatmapEndDate(
  usage.data?.generated_at,
  usage.selectedBuckets,
));
const cells = computed(() => buildHeatmapCells(
  usage.selectedBuckets,
  usage.heatmapMode,
  heatmapEndDate.value,
));
const maximum = computed(() => Math.max(
  0,
  ...(cells.value ?? []).map((cell) => cell.tokens),
));
const monthLabels = computed(() => buildHeatmapMonthLabels(cells.value ?? []));
const hasActivity = computed(() => (
  usage.selectedBuckets?.some((bucket) => bucket.tokens > 0) ?? false
));
const selectedEmail = computed(() => (
  usage.accountOptions.find(
    (account) => account.accountId === usage.selectedAccountId,
  )?.email ?? "Tài khoản không xác định"
));
const quotaStatistics = computed(() => session.state?.usage_statistics ?? null);
const accountRows = computed<AccountTableRow[]>(() => usage.accountOptions.map(
  ({ accountId, email }) => ({
    accountId,
    email,
    quota: quotaStatistics.value?.accounts.find(
      (account) => account.account_id === accountId,
    ) ?? null,
    token: usage.data?.accounts.find(
      (account) => account.account_id === accountId,
    ) ?? null,
  }),
));
const selectedFreshness = computed(() => {
  if (usage.selectedTokenAccount) return usage.selectedTokenAccount.status;
  if (usage.selectedBuckets === null) return "unavailable";
  return (usage.data?.coverage.stale_accounts ?? 0) > 0 ? "stale" : "fresh";
});
const freshnessLabel = computed(() => ({
  fresh: "Mới",
  stale: "Dữ liệu cũ",
  unavailable: "Không lấy được",
}[selectedFreshness.value]));
const freshnessDetail = computed(() => {
  if (!usage.data) return "Chưa có dữ liệu";
  if (usage.selectedTokenAccount) {
    return formatGeneratedTime(
      usage.selectedTokenAccount.updated_at ?? usage.data.generated_at,
    );
  }
  const { fresh_accounts: fresh, stale_accounts: stale, unavailable_accounts: unavailable } =
    usage.data.coverage;
  return `${formatGeneratedTime(usage.data.generated_at)} · ${fresh} mới, ${stale} cũ, ${unavailable} chưa có`;
});

watch(cells, (nextCells) => {
  if (!nextCells?.length) {
    activeCellStart.value = "";
    pointerTooltip.value = null;
    return;
  }
  if (!nextCells.some((cell) => cell.startDate === activeCellStart.value)) {
    activeCellStart.value = nextCells.at(-1)?.startDate ?? "";
  }
}, { immediate: true });

function setHeatmapMode(value: string): void {
  usage.heatmapMode = value as HeatmapMode;
}

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "—"
    : value.toLocaleString("vi-VN");
}

function formatPercent(value: number | null | undefined): string {
  return value === null || value === undefined
    ? "—"
    : `${value.toLocaleString("vi-VN", { maximumFractionDigits: 1 })}%`;
}

function formatDuration(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  const seconds = Math.max(0, Math.round(value));
  if (seconds < 60) return `${seconds} giây`;
  const hours = Math.floor(seconds / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  if (hours === 0) return `${minutes} phút`;
  return minutes > 0 ? `${hours} giờ ${minutes} phút` : `${hours} giờ`;
}

function formatDays(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `${Math.round(value)} ngày`;
}

function formatGeneratedTime(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Chưa rõ thời điểm"
    : date.toLocaleString("vi-VN");
}

function formatDate(value: string): string {
  const [year, month, day] = value.split("-");
  return `${day}/${month}/${year}`;
}

function heatmapLabel(cell: HeatmapCell): string {
  const tokens = formatNumber(cell.tokens);
  if (usage.heatmapMode === "daily") {
    return `${tokens} token · ${formatDate(cell.startDate)}`;
  }
  const prefix = usage.heatmapMode === "cumulative" ? "Lũy kế đến tuần" : "Tuần";
  return `${tokens} token · ${prefix} ${formatDate(cell.startDate)}–${formatDate(cell.endDate)}`;
}

function showHeatmapTooltip(
  cell: HeatmapCell,
  event: PointerEvent,
): void {
  pointerTooltip.value = {
    cell,
    placeLeft: event.clientX > window.innerWidth - 300,
    x: event.clientX,
    y: event.clientY - 12,
  };
}

function quotaCategory(account: AccountUsageStatistics | null): QuotaCategory {
  if (!account) return "unavailable";
  if (account.needs_attention) return "attention";
  if (account.quota_remaining_percent !== null) {
    if (account.quota_remaining_percent <= 0) return "exhausted";
    if (account.quota_remaining_percent <= 20) return "low";
  }
  if (account.quota_is_stale) return "stale";
  if (account.quota_remaining_percent === null) return "unavailable";
  return account.is_usable ? "usable" : "unavailable";
}

function quotaCategoryLabel(account: AccountUsageStatistics | null): string {
  return {
    attention: "Cần xử lý",
    exhausted: "Hết quota",
    low: "Quota thấp",
    stale: "Cần đồng bộ",
    unavailable: "Chưa có dữ liệu",
    usable: "Dùng được",
  }[quotaCategory(account)];
}

async function moveCellFocus(
  event: KeyboardEvent,
  currentIndex: number,
): Promise<void> {
  const available = cells.value ?? [];
  if (!available.length) return;
  let nextIndex = currentIndex;
  if (event.key === "ArrowRight") nextIndex += 1;
  else if (event.key === "ArrowLeft") nextIndex -= 1;
  else if (event.key === "ArrowDown") {
    nextIndex += usage.heatmapMode === "daily" ? 7 : 1;
  } else if (event.key === "ArrowUp") {
    nextIndex -= usage.heatmapMode === "daily" ? 7 : 1;
  } else if (event.key === "Home") nextIndex = 0;
  else if (event.key === "End") nextIndex = available.length - 1;
  else return;
  event.preventDefault();
  nextIndex = Math.max(0, Math.min(available.length - 1, nextIndex));
  activeCellStart.value = available[nextIndex]?.startDate ?? "";
  const grid = (event.currentTarget as HTMLElement).closest(".heatmap-grid");
  await nextTick();
  const buttons = grid?.querySelectorAll<HTMLButtonElement>(".heat-cell");
  buttons?.[nextIndex]?.focus();
}

onMounted(() => {
  void usage.fetchUsage();
});
</script>

<template>
  <section aria-label="Sử dụng token">
    <div class="panel-heading panel-heading-actions-only">
      <GlassButton
        class="usage-refresh-control"
        variant="lite"
        data-material-layer="control"
        data-control-role="refresh"
        :busy="usage.isLoading"
        @click="usage.fetchUsage(true)"
      >
        Làm mới dữ liệu
      </GlassButton>
    </div>

    <p v-if="usage.errorMessage" class="error" role="alert">{{ usage.errorMessage }}</p>

    <div class="usage-controls">
      <GlassSelectPopover
        v-model="usage.selectedAccountId"
        class="usage-account-control"
        trigger-class="usage-account-trigger"
        label="Phạm vi tài khoản"
        morph-id="usage-account-scope"
        :options="accountScopeOptions"
        data-content-role="account-selector"
      />
      <div class="usage-freshness" aria-live="polite">
        <span class="status-badge" :class="`is-${selectedFreshness}`">
          {{ usage.isLoading && !usage.data ? "Đang tải" : freshnessLabel }}
        </span>
        <span>{{ freshnessDetail }}</span>
      </div>
    </div>

    <section
      v-if="usage.selectedAccountId !== 'all'"
      class="selected-account-summary solid-content-card standard-surface"
      data-material="standard"
      data-content-role="account-summary"
      aria-labelledby="selected-account-heading"
    >
      <div>
        <p class="data-label">Tài khoản</p>
        <h3 id="selected-account-heading">{{ selectedEmail }}</h3>
      </div>
      <span class="status-badge">{{ usage.selectedQuotaAccount?.plan_type ?? "Chưa rõ gói" }}</span>
    </section>

    <div
      v-if="usage.selectedAccountId !== 'all'"
      class="token-kpis metric-grid"
      aria-label="Chỉ số sử dụng tài khoản"
    >
      <article class="usage-metric-card solid-content-card standard-surface" data-material="standard">
        <span>{{ yesterdayLabel }}</span><strong>{{ formatNumber(usage.selectedTokenAccount?.today) }}</strong>
      </article>
      <article class="usage-metric-card solid-content-card standard-surface" data-material="standard">
        <span>Tuần này</span><strong>{{ formatNumber(usage.selectedTokenAccount?.week) }}</strong>
      </article>
      <article class="usage-metric-card solid-content-card standard-surface" data-material="standard">
        <span>Tháng này</span><strong>{{ formatNumber(usage.selectedTokenAccount?.month) }}</strong>
      </article>
      <article class="usage-metric-card solid-content-card standard-surface" data-material="standard">
        <span>Lifetime tokens</span><strong>{{ formatNumber(usage.selectedTokenAccount?.lifetime) }}</strong>
      </article>
      <article class="usage-metric-card solid-content-card standard-surface" data-material="standard">
        <span>Peak tokens</span><strong>{{ formatNumber(usage.selectedTokenAccount?.peak_daily) }}</strong>
      </article>
      <article class="usage-metric-card solid-content-card standard-surface" data-material="standard">
        <span>Longest task</span><strong>{{ formatDuration(usage.selectedTokenAccount?.longest_running_turn_seconds) }}</strong>
      </article>
      <article class="usage-metric-card solid-content-card standard-surface" data-material="standard">
        <span>Current streak</span><strong>{{ formatDays(usage.selectedTokenAccount?.current_streak_days) }}</strong>
      </article>
      <article class="usage-metric-card solid-content-card standard-surface" data-material="standard">
        <span>Longest streak</span><strong>{{ formatDays(usage.selectedTokenAccount?.longest_streak_days) }}</strong>
      </article>
    </div>

    <section
      class="heatmap-card solid-content-card standard-surface"
      data-material="standard"
      data-content-role="heatmap"
      aria-labelledby="token-heatmap-title"
    >
      <div class="heatmap-heading">
        <div>
          <p class="data-label">12 tháng gần nhất</p>
          <h3 id="token-heatmap-title">
            {{ usage.heatmapMode === "daily"
              ? "Token theo ngày"
              : usage.heatmapMode === "weekly"
                ? "Token theo tuần"
                : "Token lũy kế" }}
          </h3>
        </div>
        <GlassSegmentedControl
          class="heatmap-mode-control"
          level="lite"
          data-material-layer="control"
          data-glass-container
          data-control-role="heatmap-mode"
          label="Kiểu tổng hợp heatmap"
          :model-value="usage.heatmapMode"
          :options="heatmapModes"
          @update:model-value="setHeatmapMode"
        />
      </div>

      <p v-if="cells === null" class="empty-usage">
        Dữ liệu heatmap chưa khả dụng cho phạm vi này.
      </p>
      <template v-else>
        <div class="heatmap-scroll">
          <div class="token-heatmap">
            <div
              class="heatmap-grid"
              :class="`is-${usage.heatmapMode}`"
              :style="{ gridTemplateColumns: `repeat(${Math.max(1, cells.at(-1)?.column ?? 1)}, 1fr)` }"
              role="group"
              :aria-label="`${cells.length} ô dữ liệu token, kết thúc ${formatDate(heatmapEndDate)}`"
            >
              <button
                v-for="(cell, index) in cells"
                :key="`${cell.startDate}-${usage.heatmapMode}`"
                type="button"
                class="heat-cell"
                :class="`level-${heatmapLevel(cell.tokens, maximum)}`"
                :style="{ gridColumn: cell.column, gridRow: cell.row }"
                :data-level="heatmapLevel(cell.tokens, maximum)"
                :data-start-date="cell.startDate"
                :aria-label="heatmapLabel(cell)"
                :aria-describedby="pointerTooltip?.cell.startDate === cell.startDate
                  ? 'heatmap-pointer-tooltip'
                  : undefined"
                :tabindex="cell.startDate === activeCellStart ? 0 : -1"
                @focus="activeCellStart = cell.startDate"
                @pointerenter="showHeatmapTooltip(cell, $event)"
                @pointermove="showHeatmapTooltip(cell, $event)"
                @pointerleave="pointerTooltip = null"
                @keydown="moveCellFocus($event, index)"
              >
                <span
                  v-if="usage.heatmapMode !== 'daily'"
                  class="heat-cell-stack"
                  aria-hidden="true"
                >
                  <span
                    v-for="row in 7"
                    :key="row"
                    class="heat-cell-segment"
                  />
                </span>
              </button>
            </div>
            <div
              class="heatmap-months"
              :style="{ gridTemplateColumns: `repeat(${Math.max(1, cells.at(-1)?.column ?? 1)}, 1fr)` }"
              aria-hidden="true"
            >
              <span
                v-for="label in monthLabels"
                :key="`${label.key}-${label.column}`"
                class="heatmap-month"
                :style="{ gridColumn: label.column }"
              >{{ label.label }}</span>
            </div>
          </div>
        </div>
        <Teleport to="body">
          <div
            v-if="pointerTooltip"
            id="heatmap-pointer-tooltip"
            class="heatmap-pointer-tooltip"
            :class="{ 'is-left': pointerTooltip.placeLeft }"
            role="tooltip"
            :style="{
              left: `${pointerTooltip.x + (pointerTooltip.placeLeft ? -12 : 12)}px`,
              top: `${pointerTooltip.y}px`,
            }"
          >
            {{ heatmapLabel(pointerTooltip.cell) }}
          </div>
        </Teleport>
        <p v-if="!hasActivity" class="empty-usage no-activity-notice">
          Chưa có hoạt động trong 12 tháng này.
        </p>
      </template>
    </section>

    <section
      v-if="usage.selectedAccountId !== 'all'"
      class="single-quota-card solid-content-card standard-surface"
      data-material="standard"
      data-content-role="quota-summary"
      aria-labelledby="single-quota-heading"
    >
      <div>
        <span class="data-label">Quota còn lại</span>
        <strong id="single-quota-heading" class="metric-value">
          {{ formatPercent(usage.selectedQuotaAccount?.quota_remaining_percent) }}
        </strong>
        <span>Chu kỳ: {{ usage.selectedQuotaAccount?.quota_cycle ?? "—" }}</span>
      </div>
      <dl>
        <div><dt>Reset</dt><dd>{{ usage.selectedQuotaAccount?.quota_reset_at ?? "—" }}</dd></div>
        <div><dt>Trạng thái</dt><dd>{{ quotaCategoryLabel(usage.selectedQuotaAccount) }}</dd></div>
      </dl>
    </section>

    <section
      v-if="usage.selectedAccountId === 'all'"
      class="all-account-statistics"
      aria-label="Thống kê tất cả tài khoản"
    >
      <div class="metric-grid all-token-totals" aria-label="Tổng token">
        <article
          v-for="card in allTotalCards"
          :key="card.key"
          class="all-token-total usage-metric-card solid-content-card standard-surface"
          data-material="standard"
        >
          <span>{{ card.label }}</span>
          <strong>{{ formatNumber(usage.data?.aggregate.totals[card.key]) }}</strong>
        </article>
      </div>

      <div v-if="quotaStatistics" class="quota-summary" aria-label="Tình trạng quota">
        <article
          class="usage-metric-card quota-primary-card solid-content-card standard-surface"
          data-material="standard"
        >
          <span>Quota bình quân còn lại</span>
          <strong>{{ formatPercent(quotaStatistics.average_remaining_percent) }}</strong>
          <div
            class="quota-average-progress"
            role="progressbar"
            aria-label="Quota bình quân còn lại"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-valuenow="quotaStatistics.average_remaining_percent ?? 0"
          >
            <span :style="{ width: `${quotaStatistics.average_remaining_percent ?? 0}%` }" />
          </div>
        </article>
        <article class="usage-metric-card solid-content-card standard-surface" data-material="standard">
          <span>Dùng được</span><strong>{{ quotaStatistics.usable_accounts }}</strong>
        </article>
        <article class="usage-metric-card solid-content-card standard-surface" data-material="standard">
          <span>Cần xử lý</span><strong>{{ quotaStatistics.attention_accounts }}</strong>
        </article>
        <article class="usage-metric-card solid-content-card standard-surface" data-material="standard">
          <span>Quota thấp</span><strong>{{ quotaStatistics.low_quota_accounts }}</strong>
        </article>
        <article class="usage-metric-card solid-content-card standard-surface" data-material="standard">
          <span>Hết quota</span><strong>{{ quotaStatistics.exhausted_accounts }}</strong>
        </article>
      </div>

      <div
        class="usage-table-wrap solid-content-table standard-surface"
        data-material="standard"
        data-content-role="account-table"
      >
        <table class="usage-table">
          <caption class="sr-only">Thống kê quota theo từng tài khoản</caption>
          <thead>
            <tr>
              <th scope="col">Tài khoản</th>
              <th scope="col">Gói</th>
              <th scope="col">Lifetime</th>
              <th scope="col">Peak/ngày</th>
              <th scope="col">Longest task</th>
              <th scope="col">Current streak</th>
              <th scope="col">Longest streak</th>
              <th scope="col">Quota còn lại</th>
              <th scope="col">Trạng thái</th>
              <th scope="col">Reset quota</th>
              <th scope="col">Đồng bộ cuối</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in accountRows" :key="row.accountId">
              <td data-label="Tài khoản" class="usage-account-email">{{ row.email }}</td>
              <td data-label="Gói">{{ row.quota?.plan_type ?? "—" }}</td>
              <td data-label="Lifetime">{{ formatNumber(row.token?.lifetime) }}</td>
              <td data-label="Peak/ngày">{{ formatNumber(row.token?.peak_daily) }}</td>
              <td data-label="Longest task">{{ formatDuration(row.token?.longest_running_turn_seconds) }}</td>
              <td data-label="Current streak">{{ formatDays(row.token?.current_streak_days) }}</td>
              <td data-label="Longest streak">{{ formatDays(row.token?.longest_streak_days) }}</td>
              <td data-label="Quota còn lại">{{ formatPercent(row.quota?.quota_remaining_percent) }}</td>
              <td data-label="Trạng thái">
                <span class="status-badge" :class="`is-${quotaCategory(row.quota)}`">
                  {{ quotaCategoryLabel(row.quota) }}
                </span>
              </td>
              <td data-label="Reset quota">{{ row.quota?.quota_reset_at ?? "—" }}</td>
              <td data-label="Đồng bộ cuối">{{ row.quota?.last_sync ?? "—" }}</td>
            </tr>
          </tbody>
        </table>
        <p v-if="accountRows.length === 0" class="empty-usage">Chưa có tài khoản.</p>
      </div>
    </section>
  </section>
</template>
