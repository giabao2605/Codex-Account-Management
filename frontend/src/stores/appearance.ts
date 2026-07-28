import { computed, ref } from "vue";
import { defineStore } from "pinia";

export type ThemeName = "light" | "dark";
export type ThemePreference = "system" | ThemeName;
export type EffectsPreference = "auto" | "full" | "reduced" | "off";
export type ResolvedEffects = "full" | "reduced" | "off";
export type GlassQuality = "full" | "reduced" | "off";
export type GlassMotion = "full" | "reduced";
export type GlassTransparency = "normal" | "reduced";
export type GlassContrast = "normal" | "increased" | "forced";
export type GlassInputMode = "mouse" | "touch" | "pen" | "keyboard";
export type GlassRendererMode = "svg" | "hybrid" | "solid";

export interface GlassRuntimeProfile {
  quality: GlassQuality;
  motion: GlassMotion;
  transparency: GlassTransparency;
  contrast: GlassContrast;
  input: GlassInputMode;
  renderer: GlassRendererMode;
}

export interface GlassCapabilities {
  backdropFilter: boolean;
  svgBackdropFilter: boolean;
  webGpu: boolean;
  forcedColors: boolean;
  reducedMotion: boolean;
  reducedTransparency: boolean;
  increasedContrast: boolean;
}

export const THEME_STORAGE_KEY = "otp-codex-theme";
export const THEME_PREFERENCE_STORAGE_KEY = "otp-codex-theme-preference";
export const EFFECTS_STORAGE_KEY = "otp-codex-effects";
export const THEME_TRANSITION_DURATION_MS = 240;

interface ViewTransitionHandle {
  finished: Promise<unknown>;
}

type ViewTransitionDocument = Document & {
  startViewTransition?: (
    updateCallback: () => void | Promise<void>,
  ) => ViewTransitionHandle;
};

function storageValue(key: string): string {
  try {
    return window.localStorage.getItem(key) ?? "";
  } catch {
    return "";
  }
}

function systemTheme(): ThemeName {
  return window.matchMedia?.("(prefers-color-scheme: light)").matches
    ? "light"
    : "dark";
}

function initialThemePreference(): ThemePreference {
  const storedPreference = storageValue(THEME_PREFERENCE_STORAGE_KEY);
  if (["system", "light", "dark"].includes(storedPreference)) {
    return storedPreference as ThemePreference;
  }
  const legacyTheme = storageValue(THEME_STORAGE_KEY);
  return ["light", "dark"].includes(legacyTheme)
    ? legacyTheme as ThemeName
    : "system";
}

function initialEffectsPreference(): EffectsPreference {
  const stored = storageValue(EFFECTS_STORAGE_KEY);
  return ["auto", "full", "reduced", "off"].includes(stored)
    ? stored as EffectsPreference
    : "auto";
}

export function detectGlassCapabilities(): GlassCapabilities {
  const mediaMatches = (query: string): boolean => (
    window.matchMedia?.(query).matches ?? false
  );
  const supportsCss = (
    typeof CSS !== "undefined"
    && typeof CSS.supports === "function"
  );
  const backdropFilter = supportsCss && (
    CSS.supports("backdrop-filter", "blur(1px)")
    || CSS.supports("-webkit-backdrop-filter", "blur(1px)")
  );
  const svgFilterValue = 'url("#otp-glass-capability") blur(1px)';
  const svgBackdropFilter = supportsCss && (
    CSS.supports("backdrop-filter", svgFilterValue)
    || CSS.supports("-webkit-backdrop-filter", svgFilterValue)
  );
  const gpuNavigator = navigator as Navigator & { gpu?: unknown };
  return {
    backdropFilter,
    svgBackdropFilter,
    webGpu: Boolean(gpuNavigator.gpu),
    forcedColors: mediaMatches("(forced-colors: active)"),
    reducedMotion: mediaMatches("(prefers-reduced-motion: reduce)"),
    reducedTransparency: mediaMatches(
      "(prefers-reduced-transparency: reduce)",
    ),
    increasedContrast: mediaMatches("(prefers-contrast: more)"),
  };
}

export function resolveEffects(
  preference: EffectsPreference,
  capabilities: GlassCapabilities,
): ResolvedEffects {
  if (preference === "off" || capabilities.forcedColors) {
    return "off";
  }
  if (preference === "reduced" || capabilities.reducedTransparency) {
    return "reduced";
  }
  if (!capabilities.backdropFilter) {
    return "off";
  }
  if (preference === "full" || preference === "auto") {
    return "full";
  }
  return "reduced";
}

export function resolveGlassRuntimeProfile(
  preference: EffectsPreference,
  capabilities: GlassCapabilities,
  input: GlassInputMode = "keyboard",
): GlassRuntimeProfile {
  const quality: GlassQuality = (
    preference === "off"
    || capabilities.forcedColors
    || !capabilities.backdropFilter
  )
    ? "off"
    : preference === "reduced"
      ? "reduced"
      : "full";
  const motion: GlassMotion = capabilities.reducedMotion
    ? "reduced"
    : "full";
  const transparency: GlassTransparency = (
    capabilities.reducedTransparency || capabilities.forcedColors
  )
    ? "reduced"
    : "normal";
  const contrast: GlassContrast = capabilities.forcedColors
    ? "forced"
    : capabilities.increasedContrast
      ? "increased"
      : "normal";
  const canUseOpticalRenderer = (
    quality !== "off"
    && transparency === "normal"
    && capabilities.svgBackdropFilter
  );
  const renderer: GlassRendererMode = !canUseOpticalRenderer
    ? "solid"
    : quality === "full" && capabilities.webGpu
      ? "hybrid"
      : "svg";

  return {
    quality,
    motion,
    transparency,
    contrast,
    input,
    renderer,
  };
}

function publishGlassProfile(
  profile: GlassRuntimeProfile,
  legacyEffects: ResolvedEffects,
): void {
  const root = document.documentElement;
  root.dataset.effects = legacyEffects;
  root.dataset.glassQuality = profile.quality;
  root.dataset.glassMotion = profile.motion;
  root.dataset.glassTransparency = profile.transparency;
  root.dataset.glassContrast = profile.contrast;
}

export const useAppearanceStore = defineStore("appearance", () => {
  const themePreference = ref<ThemePreference>(initialThemePreference());
  const theme = ref<ThemeName>(
    themePreference.value === "system"
      ? systemTheme()
      : themePreference.value,
  );
  const effectsPreference = ref<EffectsPreference>(
    initialEffectsPreference(),
  );
  const initialCapabilities = detectGlassCapabilities();
  const resolvedEffects = ref<ResolvedEffects>(
    resolveEffects(effectsPreference.value, initialCapabilities),
  );
  const runtimeProfile = ref<GlassRuntimeProfile>(
    resolveGlassRuntimeProfile(
      effectsPreference.value,
      initialCapabilities,
    ),
  );
  const isDark = computed(() => theme.value === "dark");
  const motionReduced = computed(
    () => runtimeProfile.value.motion === "reduced",
  );

  function applyTheme(nextTheme: ThemeName): void {
    theme.value = nextTheme;
    document.documentElement.dataset.theme = nextTheme;
    document.documentElement.style.colorScheme = nextTheme;
    const themeColor = document.querySelector<HTMLMetaElement>("#theme-color");
    if (themeColor) {
      themeColor.content = nextTheme === "light" ? "#dfe4eb" : "#090d15";
    }
    window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
  }

  function transitionTheme(nextTheme: ThemeName): void {
    const root = document.documentElement;
    // Keep the synchronous legacy key used by theme-init.js even while the
    // DOM update is captured by the browser on the next transition frame.
    window.localStorage.setItem(THEME_STORAGE_KEY, nextTheme);
    const reduceMotion = (
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false
    );
    const startViewTransition = (
      document as ViewTransitionDocument
    ).startViewTransition;
    if (
      theme.value === nextTheme
      || reduceMotion
      || typeof startViewTransition !== "function"
    ) {
      root.style.setProperty(
        "--theme-transition-duration",
        reduceMotion ? "0ms" : `${THEME_TRANSITION_DURATION_MS}ms`,
      );
      applyTheme(nextTheme);
      return;
    }

    root.style.setProperty(
      "--theme-transition-duration",
      `${THEME_TRANSITION_DURATION_MS}ms`,
    );
    root.dataset.themeTransition = "active";
    try {
      const transition = startViewTransition.call(
        document,
        () => applyTheme(nextTheme),
      );
      void transition.finished
        .catch(() => undefined)
        .finally(() => {
          delete root.dataset.themeTransition;
        });
    } catch {
      delete root.dataset.themeTransition;
      applyTheme(nextTheme);
    }
  }

  function setThemePreference(preference: ThemePreference): void {
    themePreference.value = preference;
    window.localStorage.setItem(THEME_PREFERENCE_STORAGE_KEY, preference);
    transitionTheme(preference === "system" ? systemTheme() : preference);
  }

  function setEffectsPreference(preference: EffectsPreference): void {
    effectsPreference.value = preference;
    const capabilities = detectGlassCapabilities();
    resolvedEffects.value = resolveEffects(preference, capabilities);
    runtimeProfile.value = resolveGlassRuntimeProfile(
      preference,
      capabilities,
      runtimeProfile.value.input,
    );
    publishGlassProfile(runtimeProfile.value, resolvedEffects.value);
    window.localStorage.setItem(EFFECTS_STORAGE_KEY, preference);
  }

  function refreshCapabilities(): void {
    const capabilities = detectGlassCapabilities();
    resolvedEffects.value = resolveEffects(
      effectsPreference.value,
      capabilities,
    );
    runtimeProfile.value = resolveGlassRuntimeProfile(
      effectsPreference.value,
      capabilities,
      runtimeProfile.value.input,
    );
    publishGlassProfile(runtimeProfile.value, resolvedEffects.value);
  }

  function setInputMode(input: GlassInputMode): void {
    runtimeProfile.value = {
      ...runtimeProfile.value,
      input,
    };
  }

  function toggleTheme(): void {
    setThemePreference(isDark.value ? "light" : "dark");
  }

  applyTheme(theme.value);
  publishGlassProfile(runtimeProfile.value, resolvedEffects.value);

  return {
    applyTheme,
    effectsPreference,
    isDark,
    motionReduced,
    refreshCapabilities,
    resolvedEffects,
    runtimeProfile,
    setEffectsPreference,
    setInputMode,
    setThemePreference,
    theme,
    themePreference,
    toggleTheme,
  };
});
