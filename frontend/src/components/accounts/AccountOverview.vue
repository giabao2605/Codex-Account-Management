<script setup lang="ts">
import { computed, ref } from "vue";

import GlassButton from "@/components/glass/GlassButton.vue";
import GlassPopover from "@/components/glass/GlassPopover.vue";
import SurfaceActionButton from "@/components/glass/SurfaceActionButton.vue";
import { useSessionStore } from "@/stores/session.ts";
import { syncMetrics } from "@/utils/accounts.ts";

const session = useSessionStore();
const detailsOpen = ref(false);
const state = computed(() => session.state);
const metrics = computed(() => (
  state.value
    ? syncMetrics(state.value)
    : { success: 0, login: 0, unlinked: 0, error: 0 }
));
const totalAccounts = computed(() => state.value?.accounts.length ?? 0);
const successRatio = computed(() => (
  `${metrics.value.success} / ${totalAccounts.value}`
));
const syncBreakdown = computed(() => [
  `${metrics.value.success} thành công`,
  `${metrics.value.login} cần đăng nhập`,
  `${metrics.value.unlinked} chưa liên kết`,
  `${metrics.value.error} lỗi tạm thời`,
].join(" · "));
const healthLabel = computed(() => {
  const syncIssues = (
    metrics.value.login
    + metrics.value.unlinked
    + metrics.value.error
  );
  const usage = state.value?.usage_statistics;
  if (syncIssues > 0) return `${syncIssues} tài khoản cần xử lý`;
  if (usage?.exhausted_accounts) {
    return `${usage.exhausted_accounts} tài khoản hết quota`;
  }
  if (usage?.low_quota_accounts) {
    return `${usage.low_quota_accounts} tài khoản quota thấp`;
  }
  if (usage?.quota_unknown_accounts || usage?.stale_quota_accounts) {
    return "Dữ liệu quota cần cập nhật";
  }
  return "Tất cả hoạt động bình thường";
});
const healthy = computed(() => healthLabel.value === "Tất cả hoạt động bình thường");
const timeSyncLabel = computed(() => {
  const timeSync = state.value?.time_sync;
  if (!timeSync) return "Chưa có trạng thái";
  if (timeSync.status === "synced") {
    const roundedOffset = Math.round(timeSync.offset_seconds ?? 0);
    const sign = roundedOffset > 0 ? "+" : "";
    return `Đã đồng bộ · bù ${sign}${roundedOffset} giây`;
  }
  if (timeSync.status === "syncing") return "Đang đồng bộ";
  return "Đang dùng thời gian dự phòng";
});
const lastUpdatedLabel = computed(() => (
  session.lastUpdated?.toLocaleTimeString("vi-VN", {
    hour: "2-digit",
    minute: "2-digit",
  }) ?? "Chưa cập nhật"
));
</script>

<template>
  <div class="accounts-overview" aria-label="Tổng quan tài khoản">
    <GlassPopover
      v-model:open="detailsOpen"
      class="account-overview-popover"
      label="Chi tiết trạng thái tài khoản"
      morph-id="account-status-details"
      placement="start"
    >
      <template #trigger="{ panelId }">
        <GlassButton
          variant="quiet"
          data-action="account-status-details"
          aria-label="Chi tiết trạng thái tài khoản"
          aria-haspopup="dialog"
          :aria-controls="panelId"
          :aria-expanded="detailsOpen"
        >
          Chi tiết
        </GlassButton>
      </template>
      <dl class="account-overview-details">
        <div>
          <dt>Trạng thái</dt>
          <dd
            class="account-health-status"
            :class="healthy ? 'is-healthy' : 'needs-attention'"
          >
            {{ healthLabel }}
          </dd>
        </div>
        <div>
          <dt>Tự làm mới</dt>
          <dd>{{ state?.refresh_interval_seconds ?? 0 }} giây</dd>
        </div>
        <div>
          <dt>Cập nhật gần nhất</dt>
          <dd>{{ lastUpdatedLabel }}</dd>
        </div>
        <div>
          <dt>Đồng bộ thời gian</dt>
          <dd>{{ timeSyncLabel }}</dd>
        </div>
        <div>
          <dt>Đồng bộ tài khoản</dt>
          <dd>{{ successRatio }}</dd>
        </div>
      </dl>
      <p class="account-sync-breakdown">{{ syncBreakdown }}</p>
      <SurfaceActionButton @click="detailsOpen = false">
        Đóng
      </SurfaceActionButton>
    </GlassPopover>
  </div>
</template>
