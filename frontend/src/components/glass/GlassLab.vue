<script setup lang="ts">
import { ref } from "vue";

import GlassButton from "./GlassButton.vue";
import GlassPopover from "./GlassPopover.vue";
import GlassSurface from "./GlassSurface.vue";

const referenceDate = "2026-07-27";
const isEnabled = typeof window !== "undefined"
  && new URL(window.location.href).searchParams.get("glass-lab") === "1";
const morphOpen = ref(false);
const inputMode = ref<"keyboard" | "mouse" | "touch" | "pen">("keyboard");

const scenes = [
  { id: "stripe", label: "Đường sọc", context: "text" },
  { id: "checkerboard", label: "Bàn cờ", context: "text" },
  { id: "text", label: "Nội dung chữ", context: "text" },
  { id: "white", label: "Nền trắng", context: "light" },
  { id: "black", label: "Nền đen", context: "dark" },
  { id: "color", label: "Dải màu", context: "media" },
  { id: "media", label: "Hình ảnh", context: "media" },
] as const;

function recordPointerInput(event: PointerEvent): void {
  if (
    event.pointerType === "touch"
    || event.pointerType === "pen"
    || event.pointerType === "mouse"
  ) {
    inputMode.value = event.pointerType;
    return;
  }
  inputMode.value = "mouse";
}
</script>

<template>
  <main
    v-if="isEnabled"
    class="glass-lab"
    data-testid="glass-lab"
    data-glass-lab="v3"
    aria-labelledby="glass-lab-title"
    @keydown="inputMode = 'keyboard'"
    @pointerdown="recordPointerInput"
  >
    <header class="glass-lab__header">
      <p class="glass-lab__eyebrow">Test-only Liquid Glass v3</p>
      <h1 id="glass-lab-title">Glass Lab</h1>
      <p>
        Bề mặt kiểm chứng khúc xạ, vật liệu, hình học, chuyển động và các chế độ
        truy cập. Trang này chỉ xuất hiện khi URL có <code>?glass-lab=1</code>.
      </p>
      <output
        class="glass-lab__input"
        data-testid="glass-lab-input-mode"
        aria-live="polite"
      >
        Nguồn nhập: {{ inputMode }}
      </output>
    </header>

    <aside
      class="glass-lab__references"
      data-testid="glass-lab-reference"
      aria-label="Nguồn tham chiếu"
    >
      <strong>Nguồn chuẩn:</strong>
      <a
        href="https://developer.apple.com/design/human-interface-guidelines/materials"
        rel="noreferrer"
      >
        Apple Materials
      </a>
      <a
        href="https://developer.apple.com/videos/play/wwdc2026/269/"
        rel="noreferrer"
      >
        WWDC26 SwiftUI
      </a>
      <span>
        Đối chiếu ngày
        <time :datetime="referenceDate">{{ referenceDate }}</time>.
        Các giới hạn quang học trong test là phép đo suy ra, không phải token do
        Apple công bố.
      </span>
    </aside>

    <section class="glass-lab__section" aria-labelledby="glass-lab-scenes-title">
      <h2 id="glass-lab-scenes-title">Nền kiểm chứng quang học</h2>
      <div class="glass-lab__scene-grid">
        <article
          v-for="scene in scenes"
          :key="scene.id"
          class="glass-lab__scene"
          :class="`is-${scene.id}`"
          :data-glass-context="scene.context"
          :data-testid="`glass-lab-background-${scene.id}`"
        >
          <h3>{{ scene.label }}</h3>
          <div
            v-if="scene.id === 'text'"
            class="glass-lab__text-field"
            aria-hidden="true"
          >
            Liquid Glass bẻ cong ánh sáng nhưng vẫn giữ nội dung nền có thể
            nhận biết.
          </div>
          <div class="glass-lab__optical-axis" aria-hidden="true">
            <span v-for="index in 9" :key="index" />
          </div>
          <GlassSurface
            class="glass-lab__specimen"
            :data-testid="`glass-lab-${scene.id}-regular`"
            material="regular"
            :context="scene.context"
            shape="rounded"
            depth="auto"
            concentric
            interactive
          >
            <span>Regular</span>
          </GlassSurface>
          <GlassSurface
            v-if="scene.id === 'media'"
            class="glass-lab__specimen glass-lab__specimen--clear"
            data-testid="glass-lab-media-clear"
            material="clear"
            context="media"
            shape="rounded"
            depth="auto"
            concentric
            interactive
          >
            <span>Clear</span>
          </GlassSurface>
        </article>
      </div>
    </section>

    <section
      class="glass-lab__section glass-lab__geometry"
      data-testid="glass-lab-geometry"
      aria-labelledby="glass-lab-geometry-title"
    >
      <h2 id="glass-lab-geometry-title">Hình học</h2>
      <div class="glass-lab__geometry-row">
        <GlassSurface
          data-testid="glass-lab-shape-rounded"
          material="regular"
          context="media"
          shape="rounded"
          depth="regular"
          interactive
        >
          Rounded
        </GlassSurface>
        <GlassButton
          data-testid="glass-lab-shape-capsule"
          variant="prominent"
          shape="capsule"
        >
          Capsule
        </GlassButton>
        <GlassSurface
          data-testid="glass-lab-shape-panel"
          material="regular"
          context="media"
          shape="panel"
          depth="thick"
          concentric
        >
          Panel
        </GlassSurface>
      </div>
    </section>

    <section
      class="glass-lab__section glass-lab__morph"
      data-testid="glass-lab-morph"
      aria-labelledby="glass-lab-morph-title"
    >
      <h2 id="glass-lab-morph-title">Shared material morph</h2>
      <GlassPopover
        v-model:open="morphOpen"
        label="Mẫu morph Liquid Glass"
        morph-id="glass-lab-morph"
        placement="start"
      >
        <template #trigger="{ open, panelId }">
          <GlassButton
            data-testid="glass-lab-morph-trigger"
            morph-id="glass-lab-morph"
            shape="rounded"
            :aria-expanded="open"
            :aria-controls="panelId"
          >
            Mở bề mặt
          </GlassButton>
        </template>
        <section
          class="glass-lab__morph-content"
          data-testid="glass-lab-morph-destination"
        >
          <h3>Bề mặt đích</h3>
          <p>
            Geometry mở từ control nguồn; nội dung chỉ hiện sau khi bề mặt đã
            materialize.
          </p>
          <button type="button" @click="morphOpen = false">Đóng</button>
        </section>
      </GlassPopover>
    </section>
  </main>
</template>

<style scoped>
.glass-lab {
  box-sizing: border-box;
  min-height: 100vh;
  padding: 32px;
  color: #f7f9ff;
  background:
    radial-gradient(circle at 12% 10%, rgb(74 120 255 / 44%), transparent 32%),
    radial-gradient(circle at 86% 26%, rgb(255 91 183 / 32%), transparent 34%),
    #101522;
}

.glass-lab__header,
.glass-lab__references,
.glass-lab__section {
  width: min(1180px, 100%);
  margin-inline: auto;
}

.glass-lab__header h1,
.glass-lab__section h2,
.glass-lab__scene h3 {
  margin-block: 0;
}

.glass-lab__eyebrow {
  margin-block: 0 6px;
  color: #a9c1ff;
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.12em;
  text-transform: uppercase;
}

.glass-lab__input {
  display: inline-block;
  padding: 6px 10px;
  border-radius: 9px;
  background: rgb(255 255 255 / 10%);
  color: inherit;
}

.glass-lab__references {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 16px;
  align-items: baseline;
  box-sizing: border-box;
  margin-block: 22px 34px;
  padding: 14px 16px;
  border: 1px solid rgb(255 255 255 / 18%);
  border-radius: 14px;
  background: rgb(8 12 22 / 56%);
}

.glass-lab__references a {
  color: #b7ceff;
}

.glass-lab__section {
  margin-block-end: 36px;
}

.glass-lab__section > h2 {
  margin-block-end: 14px;
}

.glass-lab__scene-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
}

.glass-lab__scene {
  position: relative;
  isolation: isolate;
  min-height: 230px;
  overflow: hidden;
  border: 1px solid rgb(255 255 255 / 18%);
  border-radius: 22px;
  color: #10131c;
  background: #dce5f4;
}

.glass-lab__scene > h3 {
  position: relative;
  z-index: 3;
  padding: 14px 16px;
  font-size: 0.86rem;
}

.glass-lab__scene.is-stripe {
  background:
    repeating-linear-gradient(
      90deg,
      #eff5ff 0 14px,
      #222a3a 14px 24px
    );
}

.glass-lab__scene.is-checkerboard {
  background:
    conic-gradient(
      from 90deg at 1px 1px,
      #eef3ff 25%,
      #273043 0 50%,
      #eef3ff 0 75%,
      #273043 0
    ) 0 0 / 28px 28px;
}

.glass-lab__scene.is-text {
  background: #f6f1e7;
}

.glass-lab__scene.is-white {
  background: #fff;
}

.glass-lab__scene.is-black {
  color: #fff;
  background: #05070b;
}

.glass-lab__scene.is-color {
  color: #fff;
  background:
    linear-gradient(118deg, #f9348d, #ff9f31 36%, #3bb9ff 68%, #6438dc);
}

.glass-lab__scene.is-media {
  color: #fff;
  background:
    linear-gradient(rgb(10 16 28 / 18%), rgb(10 16 28 / 34%)),
    url("/assets/app-background.avif") center / cover;
}

.glass-lab__text-field {
  position: absolute;
  inset: 48px 16px auto;
  max-width: 26ch;
  font: 700 1.08rem/1.45 ui-serif, Georgia, serif;
  letter-spacing: -0.01em;
}

.glass-lab__optical-axis {
  position: absolute;
  z-index: 0;
  inset: 48% 0 auto;
  display: grid;
  grid-template-columns: repeat(9, 1fr);
}

.glass-lab__optical-axis span {
  height: 3px;
  background: currentColor;
}

.glass-lab__optical-axis span:nth-child(even) {
  opacity: 0.32;
}

.glass-lab__specimen {
  position: absolute;
  z-index: 2;
  inset: 50% auto auto 50%;
  display: grid;
  width: 172px;
  height: 82px;
  place-items: center;
  transform: translate(-50%, -50%);
  font-weight: 700;
}

.glass-lab__specimen--clear {
  inset-inline-start: 72%;
}

.glass-lab__scene.is-media .glass-lab__specimen:not(
  .glass-lab__specimen--clear
) {
  inset-inline-start: 28%;
}

.glass-lab__geometry {
  padding: 20px;
  border-radius: 24px;
  background:
    linear-gradient(125deg, #ff5a8e, #9951ff 48%, #22bfe0);
}

.glass-lab__geometry-row {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 18px;
  align-items: center;
}

.glass-lab__geometry-row > :deep(*) {
  display: grid;
  min-height: 58px;
  place-items: center;
}

.glass-lab__geometry-row > :deep(.is-shape-panel) {
  min-height: 126px;
}

.glass-lab__morph {
  min-height: 260px;
  padding: 20px;
  border-radius: 24px;
  background:
    radial-gradient(circle at 22% 30%, #ef4f92, transparent 32%),
    linear-gradient(135deg, #183b74, #2b1649);
}

.glass-lab__morph-content {
  min-width: 260px;
  max-width: 340px;
}

.glass-lab__morph-content button {
  min-height: 36px;
  padding-inline: 14px;
  border: 1px solid currentColor;
  border-radius: 10px;
  color: inherit;
  background: transparent;
}

@media (max-width: 720px) {
  .glass-lab {
    padding: 20px;
  }

  .glass-lab__geometry-row {
    grid-template-columns: 1fr;
  }
}
</style>
