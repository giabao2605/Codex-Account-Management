import {
  onBeforeUnmount,
  onMounted,
  readonly,
  ref,
  type Ref,
} from "vue";

export type LiquidGlassMode = "full" | "reduced" | "off";
export type LiquidGlassShape = "capsule" | "rounded" | "panel";
export type LiquidGlassDepth = "auto" | "thin" | "regular" | "thick";
export type GlassMaterial = "regular" | "clear";
export type GlassContext = "auto" | "light" | "dark" | "text" | "media";
export type GlassRenderer = "auto" | "svg" | "hybrid";
export type LiquidGlassTint =
  | "neutral"
  | "accent"
  | "danger"
  | "success";

interface PendingPointer {
  element: HTMLElement;
  clientX: number;
  clientY: number;
  pointerType: "mouse" | "touch" | "pen";
}

interface LiquidGlassDebug {
  readonly activeFrames: number;
  readonly pendingFrames: number;
  readonly lastPointerTarget: string | null;
}

declare global {
  interface Window {
    __otpLiquidGlassDebug?: LiquidGlassDebug;
  }
}

let activeFrames = 0;
let pendingFrames = 0;
let lastPointerTarget: string | null = null;
const sharedMode = ref<LiquidGlassMode>("reduced");
let modeSubscribers = 0;
let sharedAttributeObserver: MutationObserver | null = null;
const sharedMediaQueries: MediaQueryList[] = [];

function ensureDebugContract(): void {
  if (typeof window === "undefined" || window.__otpLiquidGlassDebug) {
    return;
  }
  Object.defineProperty(window, "__otpLiquidGlassDebug", {
    configurable: true,
    value: {
      get activeFrames() {
        return activeFrames;
      },
      get pendingFrames() {
        return pendingFrames;
      },
      get lastPointerTarget() {
        return lastPointerTarget;
      },
    } satisfies LiquidGlassDebug,
  });
}

function mediaMatches(query: string): boolean {
  return typeof window !== "undefined"
    && typeof window.matchMedia === "function"
    && window.matchMedia(query).matches;
}

function supportsBackdropFilter(): boolean {
  if (typeof CSS === "undefined" || typeof CSS.supports !== "function") {
    return true;
  }
  return CSS.supports("backdrop-filter", "url(#liquid-glass-rounded)")
    || CSS.supports("-webkit-backdrop-filter", "url(#liquid-glass-rounded)")
    || CSS.supports("backdrop-filter", "blur(1px)");
}

export function resolveLiquidGlassMode(): LiquidGlassMode {
  if (typeof document === "undefined") {
    return "reduced";
  }
  const requested = document.documentElement.dataset.glassQuality
    ?? document.documentElement.dataset.effects;
  if (
    requested === "off"
    || mediaMatches("(forced-colors: active)")
  ) {
    return "off";
  }
  if (
    requested === "reduced"
    || mediaMatches("(prefers-reduced-transparency: reduce)")
    || !supportsBackdropFilter()
  ) {
    return "reduced";
  }
  return requested === "full" ? "full" : "reduced";
}

function refreshSharedMode(): void {
  sharedMode.value = resolveLiquidGlassMode();
}

function subscribeToMode(): void {
  modeSubscribers += 1;
  refreshSharedMode();
  if (modeSubscribers > 1) {
    return;
  }
  sharedAttributeObserver = new MutationObserver(refreshSharedMode);
  sharedAttributeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["data-effects", "data-glass-quality"],
  });
  if (typeof window.matchMedia !== "function") {
    return;
  }
  for (const query of [
    "(forced-colors: active)",
    "(prefers-reduced-transparency: reduce)",
  ]) {
    const mediaQuery = window.matchMedia(query);
    mediaQuery.addEventListener?.("change", refreshSharedMode);
    sharedMediaQueries.push(mediaQuery);
  }
}

function unsubscribeFromMode(): void {
  modeSubscribers = Math.max(0, modeSubscribers - 1);
  if (modeSubscribers > 0) {
    return;
  }
  sharedAttributeObserver?.disconnect();
  sharedAttributeObserver = null;
  for (const mediaQuery of sharedMediaQueries) {
    mediaQuery.removeEventListener?.("change", refreshSharedMode);
  }
  sharedMediaQueries.length = 0;
}

export function useLiquidGlass(): {
  mode: Readonly<Ref<LiquidGlassMode>>;
  trackPointer: (event: PointerEvent) => void;
  setPressed: (event: PointerEvent, pressed: boolean) => void;
  clearPointer: (event: PointerEvent) => void;
} {
  let animationFrame: number | null = null;
  let pointer: PendingPointer | null = null;

  function applyPointer(): void {
    const pending = pointer;
    pointer = null;
    animationFrame = null;
    pendingFrames = Math.max(0, pendingFrames - 1);
    if (!pending || !pending.element.isConnected) {
      return;
    }
    activeFrames += 1;
    try {
      const bounds = pending.element.getBoundingClientRect();
      const x = Math.max(
        0,
        Math.min(bounds.width || 1, pending.clientX - bounds.left),
      );
      const y = Math.max(
        0,
        Math.min(bounds.height || 1, pending.clientY - bounds.top),
      );
      const normalizedX = bounds.width ? x / bounds.width : 0.5;
      const normalizedY = bounds.height ? y / bounds.height : 0.5;
      const isDirectInput = pending.pointerType !== "mouse";
      const tiltX = isDirectInput ? 0 : (0.5 - normalizedY) * 1.6;
      const tiltY = isDirectInput ? 0 : (normalizedX - 0.5) * 1.6;

      pending.element.dataset.glassInput = pending.pointerType;
      pending.element.style.setProperty("--glass-pointer-x", `${x}px`);
      pending.element.style.setProperty("--glass-pointer-y", `${y}px`);
      pending.element.style.setProperty("--pointer-x", `${x}px`);
      pending.element.style.setProperty("--pointer-y", `${y}px`);
      pending.element.style.setProperty(
        "--glass-tilt-x",
        `${tiltX.toFixed(3)}deg`,
      );
      pending.element.style.setProperty(
        "--glass-tilt-y",
        `${tiltY.toFixed(3)}deg`,
      );
      pending.element.style.setProperty(
        "--glass-input-amplitude",
        isDirectInput ? "1" : "0.42",
      );
      lastPointerTarget = pending.element.dataset.glassDebugId
        || pending.element.getAttribute("aria-label")
        || pending.element.textContent?.trim().slice(0, 48)
        || pending.element.tagName.toLowerCase();
    } finally {
      activeFrames = Math.max(0, activeFrames - 1);
    }
  }

  function trackPointer(event: PointerEvent): void {
    if (sharedMode.value !== "full") {
      return;
    }
    pointer = {
      element: event.currentTarget as HTMLElement,
      clientX: event.clientX,
      clientY: event.clientY,
      pointerType: event.pointerType === "touch" || event.pointerType === "pen"
        ? event.pointerType
        : "mouse",
    };
    if (animationFrame !== null) {
      return;
    }
    pendingFrames += 1;
    animationFrame = requestAnimationFrame(applyPointer);
  }

  function setPressed(event: PointerEvent, pressed: boolean): void {
    const element = event.currentTarget as HTMLElement;
    if (pressed) {
      trackPointer(event);
      element.dataset.glassPressed = "";
      if (
        "setPointerCapture" in element
        && typeof element.setPointerCapture === "function"
        && event.pointerId !== undefined
      ) {
        try {
          element.setPointerCapture(event.pointerId);
        } catch {
          // Pointer capture can fail for synthetic events and detached elements.
        }
      }
    } else {
      delete element.dataset.glassPressed;
    }
  }

  function clearPointer(event: PointerEvent): void {
    delete (event.currentTarget as HTMLElement).dataset.glassPressed;
  }

  onMounted(() => {
    ensureDebugContract();
    subscribeToMode();
  });

  onBeforeUnmount(() => {
    unsubscribeFromMode();
    if (animationFrame !== null) {
      cancelAnimationFrame(animationFrame);
      animationFrame = null;
      pointer = null;
      pendingFrames = Math.max(0, pendingFrames - 1);
    }
  });

  return {
    mode: readonly(sharedMode),
    trackPointer,
    setPressed,
    clearPointer,
  };
}
