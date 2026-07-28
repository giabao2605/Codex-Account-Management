import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  detectGlassCapabilities,
  EFFECTS_STORAGE_KEY,
  type GlassCapabilities,
  type GlassRuntimeProfile,
  resolveGlassRuntimeProfile,
  resolveEffects,
  THEME_STORAGE_KEY,
  useAppearanceStore,
} from "./appearance.ts";

const FULL_CAPABILITIES: GlassCapabilities = {
  backdropFilter: true,
  svgBackdropFilter: true,
  webGpu: true,
  forcedColors: false,
  reducedMotion: false,
  reducedTransparency: false,
  increasedContrast: false,
};

function mediaQueryStub(activeQueries: string[] = []) {
  return vi.fn((query: string) => ({
    matches: activeQueries.includes(query),
    media: query,
    onchange: null,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("appearance store", () => {
  beforeEach(() => {
    document.head.innerHTML = (
      '<meta id="theme-color" name="theme-color" content="#0b1020">'
    );
    document.documentElement.dataset.theme = "dark";
    window.localStorage.clear();
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    Reflect.deleteProperty(document, "startViewTransition");
    delete document.documentElement.dataset.themeTransition;
    document.documentElement.style.removeProperty(
      "--theme-transition-duration",
    );
    for (const name of [
      "effects",
      "glassQuality",
      "glassMotion",
      "glassTransparency",
      "glassContrast",
    ]) {
      delete document.documentElement.dataset[name];
    }
  });

  it("keeps the legacy theme key and meta color in sync", () => {
    const store = useAppearanceStore();

    store.toggleTheme();

    expect(store.theme).toBe("light");
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(document.documentElement.style.colorScheme).toBe("light");
    expect(
      document.querySelector<HTMLMetaElement>("#theme-color")?.content,
    ).toBe("#dfe4eb");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("light");
  });

  it("supports applying dark mode without a meta element", () => {
    document.documentElement.dataset.theme = "light";
    document.querySelector("#theme-color")?.remove();
    const store = useAppearanceStore();

    store.applyTheme("dark");

    expect(store.isDark).toBe(true);
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
  });

  it("sets the dark meta color when the meta element exists", () => {
    document.documentElement.dataset.theme = "light";
    const store = useAppearanceStore();

    store.applyTheme("dark");

    expect(
      document.querySelector<HTMLMetaElement>("#theme-color")?.content,
    ).toBe("#090d15");
  });

  it("supports system theme and explicit effect preferences", () => {
    const store = useAppearanceStore();

    store.setThemePreference("system");
    store.setEffectsPreference("reduced");

    expect(store.themePreference).toBe("system");
    expect(store.effectsPreference).toBe("reduced");
    expect(document.documentElement.dataset.effects).toBe("reduced");
    expect(window.localStorage.getItem(EFFECTS_STORAGE_KEY)).toBe("reduced");
  });

  it("uses a 240ms View Transition for explicit theme changes", () => {
    const startViewTransition = vi.fn((update: () => void) => {
      update();
      return {
        finished: Promise.resolve(),
        ready: Promise.resolve(),
        updateCallbackDone: Promise.resolve(),
        skipTransition: vi.fn(),
      };
    });
    Object.defineProperty(document, "startViewTransition", {
      configurable: true,
      value: startViewTransition,
    });
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    const store = useAppearanceStore();

    store.setThemePreference("light");

    expect(startViewTransition).toHaveBeenCalledOnce();
    expect(store.theme).toBe("light");
    expect(
      document.documentElement.style.getPropertyValue(
        "--theme-transition-duration",
      ),
    ).toBe("240ms");
  });

  it("changes theme immediately when reduced motion is requested", () => {
    const startViewTransition = vi.fn();
    Object.defineProperty(document, "startViewTransition", {
      configurable: true,
      value: startViewTransition,
    });
    vi.stubGlobal("matchMedia", vi.fn((query: string) => ({
      matches: query === "(prefers-reduced-motion: reduce)",
      media: query,
      onchange: null,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      addListener: vi.fn(),
      removeListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })));
    const store = useAppearanceStore();

    store.setThemePreference("light");

    expect(startViewTransition).not.toHaveBeenCalled();
    expect(store.theme).toBe("light");
  });

  it("resolves Auto through accessibility and capability gates", () => {
    expect(resolveEffects("auto", {
      backdropFilter: true,
      svgBackdropFilter: true,
      webGpu: true,
      forcedColors: false,
      reducedMotion: false,
      reducedTransparency: false,
      increasedContrast: false,
    })).toBe("full");
    expect(resolveEffects("auto", {
      backdropFilter: true,
      svgBackdropFilter: true,
      webGpu: true,
      forcedColors: false,
      reducedMotion: false,
      reducedTransparency: true,
      increasedContrast: false,
    })).toBe("reduced");
    expect(resolveEffects("auto", {
      backdropFilter: false,
      svgBackdropFilter: false,
      webGpu: false,
      forcedColors: true,
      reducedMotion: false,
      reducedTransparency: false,
      increasedContrast: false,
    })).toBe("off");
  });

  it("detects independent glass and accessibility capabilities", () => {
    vi.stubGlobal("matchMedia", mediaQueryStub([
      "(prefers-reduced-motion: reduce)",
      "(prefers-contrast: more)",
    ]));
    vi.stubGlobal("CSS", {
      supports: vi.fn((property: string, value: string) => (
        property === "backdrop-filter"
        && ["blur(1px)", 'url("#otp-glass-capability") blur(1px)'].includes(
          value,
        )
      )),
    });
    vi.stubGlobal("navigator", {
      ...window.navigator,
      gpu: {},
    });

    expect(detectGlassCapabilities()).toEqual({
      backdropFilter: true,
      svgBackdropFilter: true,
      webGpu: true,
      forcedColors: false,
      reducedMotion: true,
      reducedTransparency: false,
      increasedContrast: true,
    });
  });

  it("resolves every runtime profile axis independently", () => {
    const profile = resolveGlassRuntimeProfile("auto", {
      ...FULL_CAPABILITIES,
      reducedMotion: true,
      reducedTransparency: true,
      increasedContrast: true,
    }, "touch");

    expect(profile).toEqual<GlassRuntimeProfile>({
      quality: "full",
      motion: "reduced",
      transparency: "reduced",
      contrast: "increased",
      input: "touch",
      renderer: "solid",
    });
  });

  it("uses hybrid only for full SVG-capable rendering", () => {
    expect(resolveGlassRuntimeProfile(
      "full",
      FULL_CAPABILITIES,
      "mouse",
    )).toMatchObject({
      quality: "full",
      renderer: "hybrid",
      input: "mouse",
    });
    expect(resolveGlassRuntimeProfile(
      "reduced",
      FULL_CAPABILITIES,
      "pen",
    )).toMatchObject({
      quality: "reduced",
      renderer: "svg",
      input: "pen",
    });
    expect(resolveGlassRuntimeProfile("full", {
      ...FULL_CAPABILITIES,
      svgBackdropFilter: false,
    }, "keyboard")).toMatchObject({
      quality: "full",
      renderer: "solid",
      input: "keyboard",
    });
  });

  it("forces a solid high-contrast profile without coupling motion", () => {
    expect(resolveGlassRuntimeProfile("full", {
      ...FULL_CAPABILITIES,
      forcedColors: true,
    })).toEqual<GlassRuntimeProfile>({
      quality: "off",
      motion: "full",
      transparency: "reduced",
      contrast: "forced",
      input: "keyboard",
      renderer: "solid",
    });
  });

  it("publishes the runtime profile while preserving data-effects", () => {
    vi.stubGlobal("matchMedia", mediaQueryStub([
      "(prefers-reduced-motion: reduce)",
      "(prefers-contrast: more)",
    ]));
    const store = useAppearanceStore();

    store.setEffectsPreference("reduced");
    store.setInputMode("mouse");

    expect(store.runtimeProfile).toMatchObject({
      quality: "off",
      motion: "reduced",
      contrast: "increased",
      input: "mouse",
      renderer: "solid",
    });
    expect(document.documentElement.dataset.effects).toBe("reduced");
    expect(document.documentElement.dataset.glassQuality).toBe("off");
    expect(document.documentElement.dataset.glassMotion).toBe("reduced");
    expect(document.documentElement.dataset.glassTransparency).toBe("normal");
    expect(document.documentElement.dataset.glassContrast).toBe("increased");
    expect(window.localStorage.getItem(EFFECTS_STORAGE_KEY)).toBe("reduced");
  });

  it("refreshes accessibility axes without changing the saved preference", () => {
    vi.stubGlobal("CSS", {
      supports: vi.fn(() => true),
    });
    vi.stubGlobal("matchMedia", mediaQueryStub());
    const store = useAppearanceStore();
    store.setEffectsPreference("full");

    vi.stubGlobal("matchMedia", mediaQueryStub([
      "(prefers-reduced-transparency: reduce)",
    ]));
    store.refreshCapabilities();

    expect(store.effectsPreference).toBe("full");
    expect(store.runtimeProfile.quality).toBe("full");
    expect(store.runtimeProfile.transparency).toBe("reduced");
    expect(store.runtimeProfile.renderer).toBe("solid");
    expect(document.documentElement.dataset.effects).toBe("reduced");
  });
});
