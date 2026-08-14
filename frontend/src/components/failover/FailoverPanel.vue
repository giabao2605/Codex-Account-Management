<script setup lang="ts">
import { computed, onMounted, ref } from "vue";

import { userFacingError } from "@/api/client.ts";
import GlassButton from "@/components/glass/GlassButton.vue";
import { useSessionStore } from "@/stores/session.ts";
import type { FailoverState, FailoverStatusResponse } from "@/types/api.ts";

const session = useSessionStore();
const status = ref<FailoverStatusResponse | null>(null);
const loading = ref(false);
const errorMessage = ref("");

const stateLabels: Record<FailoverState, string> = {
  disabled: "Đang tắt",
  observing: "Đang theo dõi",
  draining: "Đang chuẩn bị chuyển",
  switching: "Đang chuyển profile",
  resuming: "Đang khôi phục task",
  running: "Đang chạy sau chuyển",
  all_exhausted: "Tất cả tài khoản đã hết quota",
  blocked: "Đã dừng an toàn",
  error: "Cần kiểm tra registry",
};
const stateDescriptions: Record<FailoverState, string> = {
  disabled: "Failover chưa được bật; ứng dụng không tự chuyển tài khoản.",
  observing: "Đang quan sát quota và task đủ điều kiện.",
  draining: "Đã nhận tín hiệu hết quota và đang khóa prompt mới.",
  switching: "Đang thực hiện bước chuyển profile đã được điều phối.",
  resuming: "Đang kiểm tra khả năng tiếp tục task.",
  running: "Task đã tiếp tục sau một lần chuyển thành công.",
  all_exhausted: "Không còn tài khoản có quota để tiếp tục.",
  blocked: "Failover đã dừng vì điều kiện an toàn chưa thỏa mãn.",
  error: "Không thể đọc trạng thái failover an toàn.",
};
const stateLabel = computed(() => (
  !status.value
    ? "Chưa tải"
    : !status.value.available
      ? status.value.has_error ? "Không đọc được registry" : "Chưa có registry"
      : stateLabels[status.value.state]
));
const stateDescription = computed(() => (
  !status.value
    ? ""
    : !status.value.available
      ? status.value.has_error
        ? "Registry failover không hợp lệ hoặc tạm thời không thể đọc."
        : "Failover chưa từng được khởi tạo; màn hình không tạo registry mới."
      : stateDescriptions[status.value.state]
));
const updatedAt = computed(() => {
  if (!status.value?.updated_at) return "Chưa có thay đổi";
  const parsed = new Date(status.value.updated_at);
  return Number.isNaN(parsed.getTime())
    ? "Chưa rõ"
    : parsed.toLocaleString("vi-VN");
});

async function loadStatus(): Promise<void> {
  if (loading.value) return;
  loading.value = true;
  errorMessage.value = "";
  try {
    status.value = await session.getClient().failoverStatus();
  } catch (error) {
    errorMessage.value = userFacingError(
      error,
      "Không thể tải trạng thái failover.",
    );
  } finally {
    loading.value = false;
  }
}

onMounted(() => void loadStatus());
</script>

<template>
  <section class="failover-shell" aria-labelledby="failover-heading">
    <div class="panel-heading">
      <div>
        <p class="data-label">Metadata an toàn</p>
        <h2 id="failover-heading">Trạng thái failover</h2>
      </div>
      <GlassButton
        variant="quiet"
        data-action="refresh-failover"
        :busy="loading"
        @click="loadStatus"
      >
        Làm mới
      </GlassButton>
    </div>

    <p class="failover-privacy-note">
      Màn hình chỉ hiển thị metadata tổng hợp; không đọc prompt, nội dung task,
      thư mục làm việc, thông tin đăng nhập hoặc mã tài khoản nội bộ.
    </p>
    <p v-if="errorMessage" class="error" role="alert">{{ errorMessage }}</p>

    <section
      class="failover-state-card solid-content-card standard-surface"
      data-material="standard"
      aria-live="polite"
    >
      <div>
        <span class="data-label">Trạng thái hiện tại</span>
        <strong>{{ stateLabel }}</strong>
      </div>
      <p>{{ stateDescription }}</p>
      <span>Cập nhật: {{ updatedAt }}</span>
    </section>

    <div v-if="status" class="metric-grid failover-metrics">
      <article class="usage-metric-card solid-content-card standard-surface">
        <span>Tổng task</span><strong>{{ status.tasks.total }}</strong>
      </article>
      <article class="usage-metric-card solid-content-card standard-surface">
        <span>Task đang hoạt động</span><strong>{{ status.tasks.active }}</strong>
      </article>
      <article class="usage-metric-card solid-content-card standard-surface">
        <span>Đủ điều kiện</span><strong>{{ status.tasks.eligible }}</strong>
      </article>
      <article class="usage-metric-card solid-content-card standard-surface">
        <span>Bị chặn</span><strong>{{ status.tasks.blocked }}</strong>
      </article>
      <article class="usage-metric-card solid-content-card standard-surface">
        <span>Task hết quota</span><strong>{{ status.tasks.quota_exhausted }}</strong>
      </article>
      <article class="usage-metric-card solid-content-card standard-surface">
        <span>Tài khoản hết quota</span><strong>{{ status.quotas.exhausted }}</strong>
      </article>
    </div>
  </section>
</template>
