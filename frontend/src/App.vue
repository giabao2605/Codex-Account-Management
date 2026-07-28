<script setup lang="ts">
import {
  computed,
  defineAsyncComponent,
  onBeforeUnmount,
  onMounted,
  ref,
  useTemplateRef,
} from "vue";

import AppearancePopover from "@/components/glass/AppearancePopover.vue";
import FeedbackToast from "@/components/feedback/FeedbackToast.vue";
import GlassButton from "@/components/glass/GlassButton.vue";
import GlassSegmentedControl from "@/components/glass/GlassSegmentedControl.vue";
import LiquidGlassDefs from "@/components/glass/LiquidGlassDefs.vue";
import OfflineBanner from "@/components/feedback/OfflineBanner.vue";
import { useFeedbackStore } from "@/stores/feedback.ts";
import { useSessionStore } from "@/stores/session.ts";

const AccountsPanel = defineAsyncComponent(
  () => import("@/components/accounts/AccountsPanel.vue"),
);
const UsagePanel = defineAsyncComponent(
  () => import("@/components/usage/UsagePanel.vue"),
);
const GlassLab = defineAsyncComponent(
  () => import("@/components/glass/GlassLab.vue"),
);
const props = defineProps<{ accessToken: string }>();
const isGlassLab = new URL(window.location.href).searchParams.get(
  "glass-lab",
) === "1";
type WorkspaceTab = "accounts" | "usage";
const tabs = [
  { value: "accounts", label: "Tài khoản", id: "accounts-tab", controls: "accounts-panel" },
  { value: "usage", label: "Sử dụng", id: "usage-tab", controls: "usage-panel" },
];
const activeTab = ref<WorkspaceTab>("accounts");
const usagePanelMounted = ref(false);
const feedback = useFeedbackStore();
const session = useSessionStore();
const shutdownBusy = ref(false);
const isCommandLayerOverContent = ref(false);
const commandScrollSentinel = useTemplateRef<HTMLElement>(
  "command-scroll-sentinel",
);
let commandLayerObserver: InstanceType<typeof window.IntersectionObserver>
  | undefined;
const connectionLabel = computed(() => ({
  booting: "Đang kết nối",
  ready: "Đã kết nối",
  offline: "Mất kết nối",
  incompatible: "Sai phiên bản",
  stopping: "Đang tắt",
})[session.connectionStatus]);

function selectTab(tab: WorkspaceTab): void {
  if (tab === "usage") usagePanelMounted.value = true;
  activeTab.value = tab;
  window.dispatchEvent(new window.Event("glass-context-refresh"));
}
const activeTabModel = computed({
  get: () => activeTab.value,
  set: (value: string) => selectTab(value as WorkspaceTab),
});
async function shutdown(): Promise<void> {
  if (!window.confirm("Tắt trình quản lý local?")) return;
  shutdownBusy.value = true;
  try {
    await session.shutdown();
    feedback.success("Trình quản lý đã nhận yêu cầu tắt. Bạn có thể đóng tab này.");
  } catch {
    feedback.error("Không thể tắt trình quản lý. Kết nối đã được khôi phục.");
  } finally {
    shutdownBusy.value = false;
  }
}

function observeCommandLayer(): void {
  const sentinel = commandScrollSentinel.value;
  if (!sentinel || typeof window.IntersectionObserver === "undefined") return;
  commandLayerObserver = new window.IntersectionObserver(([entry]) => {
    if (!entry) return;
    isCommandLayerOverContent.value = !entry.isIntersecting;
  }, {
    threshold: [0, 1],
  });
  commandLayerObserver.observe(sentinel);
}

onMounted(async () => {
  if (isGlassLab) return;
  observeCommandLayer();
  await session.bootstrap(props.accessToken);
  if (session.connectionStatus === "ready") session.startPolling(1_000);
});
onBeforeUnmount(() => {
  if (isGlassLab) return;
  commandLayerObserver?.disconnect();
  session.stopPolling();
});
</script>

<template>
  <LiquidGlassDefs />
  <GlassLab v-if="isGlassLab" />
  <template v-else>
    <main class="shell">
      <header class="app-content-header">
        <h1>Tài khoản Codex</h1>
        <p class="subtitle">Quản lý profile, quota và mức sử dụng token trên máy này.</p>
      </header>

      <div
        ref="command-scroll-sentinel"
        class="command-scroll-sentinel"
        aria-hidden="true"
      />
      <nav
        class="app-command-layer"
        aria-label="Điều khiển ứng dụng"
        :data-over-content="String(isCommandLayerOverContent)"
        :data-scroll-edge="activeTab === 'usage' ? 'hard' : 'soft'"
      >
        <GlassSegmentedControl
          v-model="activeTabModel"
          class="workspace-tabs"
          mode="tabs"
          label="Khu vực làm việc"
          :options="tabs"
        />
        <div class="header-actions app-system-controls">
          <AppearancePopover />
          <GlassButton
            variant="danger"
            :busy="shutdownBusy"
            :disabled="session.connectionStatus !== 'ready'"
            @click="shutdown"
          >
            Tắt ứng dụng
          </GlassButton>
        </div>
        <span
          class="connection"
          :class="`is-${session.connectionStatus}`"
          data-surface="standard"
          aria-live="polite"
        >
          {{ connectionLabel }}
        </span>
      </nav>

      <OfflineBanner v-if="session.connectionStatus === 'offline'" />
      <section
        v-if="session.connectionStatus === 'incompatible'"
        class="fatal"
        role="alert"
      >
        {{ session.errorMessage }}
      </section>
      <div v-else class="workspace-panels">
        <section
          id="accounts-panel"
          class="workspace-panel"
          role="tabpanel"
          aria-labelledby="accounts-tab"
          :aria-hidden="activeTab !== 'accounts'"
          :data-active="activeTab === 'accounts'"
          :inert="activeTab !== 'accounts'"
        >
          <AccountsPanel />
        </section>
        <section
          id="usage-panel"
          class="workspace-panel"
          role="tabpanel"
          aria-labelledby="usage-tab"
          :aria-hidden="activeTab !== 'usage'"
          :data-active="activeTab === 'usage'"
          :inert="activeTab !== 'usage'"
        >
          <UsagePanel v-if="usagePanelMounted" />
        </section>
      </div>
    </main>
    <FeedbackToast />
  </template>
</template>
