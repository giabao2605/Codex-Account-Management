import {
  onBeforeUnmount,
  onMounted,
  readonly,
  ref,
  toValue,
  type MaybeRefOrGetter,
  type Ref,
} from "vue";

import type { GlassContext } from "./useLiquidGlass.ts";

export interface RgbColor {
  readonly red: number;
  readonly green: number;
  readonly blue: number;
}

export interface RgbaColor extends RgbColor {
  readonly alpha: number;
}

export type GlassGlyphMode = "light" | "dark";

interface WallpaperSampler {
  readonly width: number;
  readonly height: number;
  sample: (x: number, y: number) => RgbColor | null;
}

let wallpaperSamplerPromise: Promise<WallpaperSampler | null> | null = null;

function clampByte(value: number): number {
  return Math.max(0, Math.min(255, Math.round(value)));
}

export function parseCssColor(value: string): RgbaColor | null {
  const normalized = value.trim().toLowerCase();
  if (!normalized || normalized === "transparent") return null;
  const match = normalized.match(
    /^rgba?\(\s*([\d.]+)\s*[, ]\s*([\d.]+)\s*[, ]\s*([\d.]+)(?:\s*[,/]\s*([\d.]+))?\s*\)$/,
  );
  if (!match) return null;
  const alpha = match[4] === undefined ? 1 : Number(match[4]);
  if (!Number.isFinite(alpha) || alpha <= 0) return null;
  return {
    red: clampByte(Number(match[1])),
    green: clampByte(Number(match[2])),
    blue: clampByte(Number(match[3])),
    alpha: Math.max(0, Math.min(1, alpha)),
  };
}

export function relativeLuminance(color: RgbColor): number {
  const linear = (channel: number): number => {
    const value = clampByte(channel) / 255;
    return value <= 0.04045
      ? value / 12.92
      : ((value + 0.055) / 1.055) ** 2.4;
  };
  return (
    linear(color.red) * 0.2126
    + linear(color.green) * 0.7152
    + linear(color.blue) * 0.0722
  );
}

export function sampleNinePointAverage(
  samples: readonly RgbColor[],
): RgbColor {
  if (samples.length !== 9) {
    throw new Error("Liquid Glass context sampling requires nine samples.");
  }
  const total = samples.reduce(
    (next, color) => ({
      red: next.red + color.red,
      green: next.green + color.green,
      blue: next.blue + color.blue,
    }),
    { red: 0, green: 0, blue: 0 },
  );
  return {
    red: Math.round(total.red / 9),
    green: Math.round(total.green / 9),
    blue: Math.round(total.blue / 9),
  };
}

export function resolveGlyphMode(
  previous: GlassGlyphMode,
  luminance: number,
): GlassGlyphMode {
  if (previous === "light" && luminance > 0.58) return "dark";
  if (previous === "dark" && luminance < 0.42) return "light";
  return previous;
}

function semanticColor(context: GlassContext): RgbColor | null {
  if (context === "light") return { red: 236, green: 241, blue: 247 };
  if (context === "dark") return { red: 14, green: 20, blue: 31 };
  return null;
}

function sampleElementBackground(
  glassElement: HTMLElement,
  x: number,
  y: number,
): RgbColor | null {
  if (typeof document.elementsFromPoint !== "function") return null;
  for (const candidate of document.elementsFromPoint(x, y)) {
    if (
      candidate === glassElement
      || glassElement.contains(candidate)
    ) {
      continue;
    }
    const element = candidate as HTMLElement;
    const explicit = semanticColor(
      (element.dataset.glassContext ?? "auto") as GlassContext,
    );
    if (explicit) return explicit;
    if (
      element.dataset.material === "standard"
      || element.dataset.glassContext
    ) {
      const color = parseCssColor(getComputedStyle(element).backgroundColor);
      if (color) return color;
    }
  }
  return null;
}

function createWallpaperSampler(): Promise<WallpaperSampler | null> {
  if (typeof Image === "undefined") return Promise.resolve(null);
  return new Promise((resolve) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => {
      const canvas = typeof OffscreenCanvas === "function"
        ? new OffscreenCanvas(image.naturalWidth, image.naturalHeight)
        : document.createElement("canvas");
      canvas.width = image.naturalWidth;
      canvas.height = image.naturalHeight;
      const context = canvas.getContext(
        "2d",
        { willReadFrequently: true },
      ) as CanvasRenderingContext2D | OffscreenCanvasRenderingContext2D | null;
      if (!context) {
        resolve(null);
        return;
      }
      context.drawImage(image, 0, 0);
      resolve({
        width: image.naturalWidth,
        height: image.naturalHeight,
        sample(x, y) {
          try {
            const data = context.getImageData(
              Math.max(0, Math.min(image.naturalWidth - 1, Math.round(x))),
              Math.max(0, Math.min(image.naturalHeight - 1, Math.round(y))),
              1,
              1,
            ).data;
            return {
              red: data[0] ?? 128,
              green: data[1] ?? 128,
              blue: data[2] ?? 128,
            };
          } catch {
            return null;
          }
        },
      });
    };
    image.onerror = () => resolve(null);
    image.src = "/assets/app-background.avif";
  });
}

async function wallpaperColorAt(
  clientX: number,
  clientY: number,
): Promise<RgbColor | null> {
  wallpaperSamplerPromise ??= createWallpaperSampler();
  const sampler = await wallpaperSamplerPromise;
  if (!sampler) return null;
  const scale = Math.max(
    window.innerWidth / sampler.width,
    window.innerHeight / sampler.height,
  );
  const renderedWidth = sampler.width * scale;
  const renderedHeight = sampler.height * scale;
  const offsetX = (renderedWidth - window.innerWidth) / 2;
  const offsetY = (renderedHeight - window.innerHeight) / 2;
  return sampler.sample(
    (clientX + offsetX) / scale,
    (clientY + offsetY) / scale,
  );
}

export function useGlassContext(
  element: Readonly<Ref<HTMLElement | null>>,
  requestedContext: MaybeRefOrGetter<GlassContext>,
): {
  ambient: Readonly<Ref<RgbColor>>;
  luminance: Readonly<Ref<number>>;
  glyphMode: Readonly<Ref<GlassGlyphMode>>;
  refresh: () => void;
} {
  const ambient = ref<RgbColor>({ red: 128, green: 128, blue: 128 });
  const luminance = ref(relativeLuminance(ambient.value));
  const glyphMode = ref<GlassGlyphMode>("light");
  let scheduledFrame: number | null = null;
  let resizeObserver: ResizeObserver | null = null;

  async function sample(): Promise<void> {
    scheduledFrame = null;
    const target = element.value;
    if (!target?.isConnected) return;
    const context = toValue(requestedContext);
    const explicit = semanticColor(context);
    const bounds = target.getBoundingClientRect();
    const samples: RgbColor[] = [];
    for (const yRatio of [0.2, 0.5, 0.8]) {
      for (const xRatio of [0.2, 0.5, 0.8]) {
        const x = bounds.left + bounds.width * xRatio;
        const y = bounds.top + bounds.height * yRatio;
        const color = explicit
          ?? sampleElementBackground(target, x, y)
          ?? await wallpaperColorAt(x, y)
          ?? ambient.value;
        samples.push(color);
      }
    }
    const nextAmbient = sampleNinePointAverage(samples);
    const nextLuminance = relativeLuminance(nextAmbient);
    ambient.value = nextAmbient;
    luminance.value = nextLuminance;
    glyphMode.value = resolveGlyphMode(glyphMode.value, nextLuminance);
    target.style.setProperty(
      "--glass-ambient-rgb",
      `${nextAmbient.red} ${nextAmbient.green} ${nextAmbient.blue}`,
    );
    target.style.setProperty(
      "--glass-ambient-luma",
      nextLuminance.toFixed(4),
    );
    target.style.setProperty(
      "--glass-media-dim",
      Math.min(0.35, Math.max(0, (nextLuminance - 0.58) * 0.7)).toFixed(3),
    );
    target.dataset.glassGlyph = glyphMode.value;
  }

  function refresh(): void {
    if (scheduledFrame !== null) return;
    scheduledFrame = requestAnimationFrame(() => {
      void sample();
    });
  }

  onMounted(() => {
    refresh();
    window.addEventListener("scroll", refresh, { passive: true });
    window.addEventListener("resize", refresh, { passive: true });
    window.addEventListener("glass-context-refresh", refresh);
    if (typeof ResizeObserver === "function" && element.value) {
      resizeObserver = new ResizeObserver(refresh);
      resizeObserver.observe(element.value);
    }
  });

  onBeforeUnmount(() => {
    window.removeEventListener("scroll", refresh);
    window.removeEventListener("resize", refresh);
    window.removeEventListener("glass-context-refresh", refresh);
    resizeObserver?.disconnect();
    if (scheduledFrame !== null) cancelAnimationFrame(scheduledFrame);
  });

  return {
    ambient: readonly(ambient),
    luminance: readonly(luminance),
    glyphMode: readonly(glyphMode),
    refresh,
  };
}
