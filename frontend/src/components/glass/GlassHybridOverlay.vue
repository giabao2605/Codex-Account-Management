<script setup lang="ts">
import {
  computed,
  onBeforeUnmount,
  onMounted,
  reactive,
  useId,
  useTemplateRef,
  watch,
} from "vue";

type HybridRenderer = "none" | "webgpu" | "2d" | "svg";

export interface GlassHybridOverlayMetrics {
  scheduledFrames: number;
  completedFrames: number;
  canvasDraws: number;
  gpuDraws: number;
  fallbackDraws: number;
  lastRenderer: HybridRenderer;
}

interface GpuRenderPassLike {
  setPipeline: (pipeline: unknown) => void;
  draw: (vertexCount: number) => void;
  end: () => void;
}

interface GpuCommandEncoderLike {
  beginRenderPass: (
    descriptor: Record<string, unknown>,
  ) => GpuRenderPassLike;
  finish: () => unknown;
}

interface GpuDeviceLike {
  createShaderModule: (descriptor: { code: string }) => unknown;
  createRenderPipeline: (
    descriptor: Record<string, unknown>,
  ) => unknown;
  createCommandEncoder: () => GpuCommandEncoderLike;
  queue: {
    submit: (commands: unknown[]) => void;
  };
}

interface GpuAdapterLike {
  requestDevice: () => Promise<GpuDeviceLike>;
}

interface GpuCanvasContextLike {
  configure: (descriptor: Record<string, unknown>) => void;
  getCurrentTexture: () => {
    createView: () => unknown;
  };
}

interface GpuLike {
  requestAdapter: () => Promise<GpuAdapterLike | null>;
  getPreferredCanvasFormat: () => string;
}

const props = withDefaults(defineProps<{
  active?: boolean;
  width?: number;
  height?: number;
  intensity?: number;
  tint?: string;
}>(), {
  active: false,
  width: 0,
  height: 0,
  intensity: 0.68,
  tint: "184, 225, 255",
});

const root = useTemplateRef<HTMLElement>("root");
const canvas = useTemplateRef<HTMLCanvasElement>("canvas");
const gradientId = `glass-hybrid-${useId().replaceAll(":", "")}`;
const metrics = reactive<GlassHybridOverlayMetrics>({
  scheduledFrames: 0,
  completedFrames: 0,
  canvasDraws: 0,
  gpuDraws: 0,
  fallbackDraws: 0,
  lastRenderer: props.active ? "svg" : "none",
});
const safeIntensity = computed(() => Math.min(
  Math.max(Number.isFinite(props.intensity) ? props.intensity : 0.68, 0),
  1,
));
const tintChannels = computed<readonly [number, number, number]>(() => {
  const channels = props.tint
    .split(",")
    .map((channel) => Number.parseFloat(channel.trim()));
  if (
    channels.length !== 3
    || channels.some((channel) => !Number.isFinite(channel))
  ) {
    return [184, 225, 255];
  }
  return channels.map(
    (channel) => Math.min(Math.max(channel, 0), 255),
  ) as unknown as readonly [number, number, number];
});
const tintCss = computed(
  () => `rgb(${tintChannels.value.join(" ")})`,
);

let frameId: number | null = null;
let renderGeneration = 0;
let resizeObserver: {
  observe: (target: HTMLElement) => void;
  disconnect: () => void;
} | null = null;
let disposed = false;

function logicalSize(target: HTMLCanvasElement): {
  width: number;
  height: number;
  dpr: number;
} {
  const measuredWidth = root.value?.clientWidth || target.clientWidth || 1;
  const measuredHeight = root.value?.clientHeight || target.clientHeight || 1;
  const width = props.width > 0 ? props.width : measuredWidth;
  const height = props.height > 0 ? props.height : measuredHeight;
  const rawDpr = Number.isFinite(window.devicePixelRatio)
    ? window.devicePixelRatio
    : 1;
  return {
    width: Math.max(1, width),
    height: Math.max(1, height),
    dpr: Math.min(Math.max(rawDpr, 0.5), 1.5),
  };
}

function resizeCanvas(
  target: HTMLCanvasElement,
  size: ReturnType<typeof logicalSize>,
): void {
  target.width = Math.max(1, Math.round(size.width * size.dpr));
  target.height = Math.max(1, Math.round(size.height * size.dpr));
}

function shaderSource(): string {
  const [red, green, blue] = tintChannels.value.map(
    (channel) => (channel / 255).toFixed(6),
  );
  return `
struct VertexOutput {
  @builtin(position) position: vec4f,
  @location(0) uv: vec2f,
}

@vertex
fn vertexMain(@builtin(vertex_index) index: u32) -> VertexOutput {
  var positions = array<vec2f, 3>(
    vec2f(-1.0, -1.0),
    vec2f(3.0, -1.0),
    vec2f(-1.0, 3.0),
  );
  var output: VertexOutput;
  let position = positions[index];
  output.position = vec4f(position, 0.0, 1.0);
  output.uv = position * 0.5 + vec2f(0.5);
  return output;
}

@fragment
fn fragmentMain(input: VertexOutput) -> @location(0) vec4f {
  let tint = vec3f(${red}, ${green}, ${blue});
  let radius = distance(input.uv, vec2f(0.5, 0.5));
  let body = 1.0 - smoothstep(0.06, 0.72, radius);
  let rim = pow(max(0.0, 1.0 - abs(radius - 0.42) * 7.0), 2.0);
  let specular = pow(
    max(0.0, 1.0 - distance(input.uv, vec2f(0.31, 0.21)) * 2.2),
    8.0,
  );
  let alpha = (
    body * 0.07 + rim * 0.13 + specular * 0.24
  ) * ${safeIntensity.value.toFixed(6)};
  return vec4f(tint * mix(0.72, 1.16, specular), alpha);
}`;
}

async function drawWebGpu(
  target: HTMLCanvasElement,
  generation: number,
): Promise<boolean> {
  const gpuNavigator = navigator as unknown as { gpu?: GpuLike };
  const gpu = gpuNavigator.gpu;
  if (!gpu) return false;

  try {
    const adapter = await gpu.requestAdapter();
    if (!adapter || disposed || generation !== renderGeneration) return false;
    const device = await adapter.requestDevice();
    if (disposed || generation !== renderGeneration) return false;
    const context = target.getContext(
      "webgpu",
    ) as unknown as GpuCanvasContextLike | null;
    if (!context) return false;

    const format = gpu.getPreferredCanvasFormat();
    context.configure({
      device,
      format,
      alphaMode: "premultiplied",
    });
    const shader = device.createShaderModule({ code: shaderSource() });
    const pipeline = device.createRenderPipeline({
      layout: "auto",
      vertex: {
        module: shader,
        entryPoint: "vertexMain",
      },
      fragment: {
        module: shader,
        entryPoint: "fragmentMain",
        targets: [{
          format,
          blend: {
            color: {
              srcFactor: "src-alpha",
              dstFactor: "one-minus-src-alpha",
              operation: "add",
            },
            alpha: {
              srcFactor: "one",
              dstFactor: "one-minus-src-alpha",
              operation: "add",
            },
          },
        }],
      },
      primitive: { topology: "triangle-list" },
    });
    const encoder = device.createCommandEncoder();
    const pass = encoder.beginRenderPass({
      colorAttachments: [{
        view: context.getCurrentTexture().createView(),
        clearValue: { r: 0, g: 0, b: 0, a: 0 },
        loadOp: "clear",
        storeOp: "store",
      }],
    });
    pass.setPipeline(pipeline);
    pass.draw(3);
    pass.end();
    device.queue.submit([encoder.finish()]);
    metrics.gpuDraws += 1;
    metrics.lastRenderer = "webgpu";
    return true;
  } catch {
    return false;
  }
}

function drawCanvas2d(
  target: HTMLCanvasElement,
  size: ReturnType<typeof logicalSize>,
): boolean {
  const context = target.getContext("2d");
  if (!context) return false;
  const [red, green, blue] = tintChannels.value;
  const rgb = `${red}, ${green}, ${blue}`;
  const intensity = safeIntensity.value;

  context.setTransform(size.dpr, 0, 0, size.dpr, 0, 0);
  context.clearRect(0, 0, size.width, size.height);
  const glow = context.createRadialGradient(
    size.width * 0.31,
    size.height * 0.21,
    0,
    size.width * 0.42,
    size.height * 0.5,
    Math.max(size.width, size.height) * 0.72,
  );
  glow.addColorStop(0, `rgba(${rgb}, ${0.3 * intensity})`);
  glow.addColorStop(0.44, `rgba(${rgb}, ${0.11 * intensity})`);
  glow.addColorStop(1, `rgba(${rgb}, 0)`);
  context.fillStyle = glow;
  context.fillRect(0, 0, size.width, size.height);

  const caustic = context.createLinearGradient(
    0,
    0,
    size.width,
    size.height,
  );
  caustic.addColorStop(0, `rgba(255, 255, 255, ${0.16 * intensity})`);
  caustic.addColorStop(0.48, "rgba(255, 255, 255, 0)");
  caustic.addColorStop(1, `rgba(${rgb}, ${0.1 * intensity})`);
  context.globalCompositeOperation = "screen";
  context.fillStyle = caustic;
  context.fillRect(0, 0, size.width, size.height);
  context.globalCompositeOperation = "source-over";

  metrics.canvasDraws += 1;
  metrics.lastRenderer = "2d";
  return true;
}

async function renderFrame(generation: number): Promise<void> {
  const target = canvas.value;
  if (!target || !props.active || disposed) return;
  const size = logicalSize(target);
  resizeCanvas(target, size);

  metrics.fallbackDraws += 1;
  metrics.lastRenderer = "svg";
  const usedGpu = await drawWebGpu(target, generation);
  if (disposed || generation !== renderGeneration || !props.active) return;
  if (!usedGpu && !drawCanvas2d(target, size)) {
    metrics.lastRenderer = "svg";
  }
  metrics.completedFrames += 1;
}

function stopPendingRender(): void {
  renderGeneration += 1;
  if (frameId !== null) {
    cancelAnimationFrame(frameId);
    frameId = null;
  }
}

function renderOnce(): void {
  renderGeneration += 1;
  if (!props.active || disposed) {
    if (!props.active) metrics.lastRenderer = "none";
    if (frameId !== null) {
      cancelAnimationFrame(frameId);
      frameId = null;
    }
    return;
  }
  if (metrics.lastRenderer === "none") metrics.lastRenderer = "svg";
  if (frameId !== null) return;

  metrics.scheduledFrames += 1;
  frameId = requestAnimationFrame(() => {
    frameId = null;
    const generation = renderGeneration;
    void renderFrame(generation);
  });
}

watch(
  () => [
    props.active,
    props.width,
    props.height,
    props.intensity,
    props.tint,
  ],
  renderOnce,
);

onMounted(() => {
  if (typeof window.ResizeObserver === "function" && root.value) {
    resizeObserver = new window.ResizeObserver(renderOnce);
    resizeObserver.observe(root.value);
  }
  renderOnce();
});

onBeforeUnmount(() => {
  disposed = true;
  stopPendingRender();
  resizeObserver?.disconnect();
  resizeObserver = null;
});

defineExpose({
  metrics,
  renderOnce,
});
</script>

<template>
  <span
    v-show="active"
    ref="root"
    class="glass-hybrid-overlay"
    aria-hidden="true"
    :data-glass-hybrid-renderer="metrics.lastRenderer"
  >
    <canvas
      v-show="metrics.lastRenderer !== 'svg'"
      ref="canvas"
      class="glass-hybrid-overlay-canvas"
    />
    <svg
      v-if="metrics.lastRenderer === 'svg'"
      class="glass-hybrid-overlay-svg"
      data-glass-hybrid-fallback="svg"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
    >
      <defs>
        <radialGradient :id="gradientId" cx="31%" cy="21%" r="74%">
          <stop
            offset="0"
            :stop-color="tintCss"
            :stop-opacity="0.3 * safeIntensity"
          />
          <stop
            offset="0.46"
            :stop-color="tintCss"
            :stop-opacity="0.1 * safeIntensity"
          />
          <stop offset="1" :stop-color="tintCss" stop-opacity="0" />
        </radialGradient>
        <linearGradient :id="`${gradientId}-rim`" x1="0" y1="0" x2="1" y2="1">
          <stop
            offset="0"
            stop-color="white"
            :stop-opacity="0.15 * safeIntensity"
          />
          <stop offset="0.48" stop-color="white" stop-opacity="0" />
          <stop
            offset="1"
            :stop-color="tintCss"
            :stop-opacity="0.1 * safeIntensity"
          />
        </linearGradient>
      </defs>
      <rect width="100" height="100" :fill="`url(#${gradientId})`" />
      <rect
        width="100"
        height="100"
        :fill="`url(#${gradientId}-rim)`"
        style="mix-blend-mode: screen"
      />
    </svg>
  </span>
</template>

<style scoped>
.glass-hybrid-overlay {
  position: absolute;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  border-radius: inherit;
  contain: strict;
  pointer-events: none;
}

.glass-hybrid-overlay-canvas,
.glass-hybrid-overlay-svg {
  display: block;
  width: 100%;
  height: 100%;
}
</style>
