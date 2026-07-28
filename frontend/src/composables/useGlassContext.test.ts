import { describe, expect, it } from "vitest";

import {
  parseCssColor,
  relativeLuminance,
  resolveGlyphMode,
  sampleNinePointAverage,
} from "./useGlassContext.ts";

describe("Liquid Glass context sampling", () => {
  it("parses opaque and alpha CSS colors without mutating inputs", () => {
    expect(parseCssColor("rgb(12, 34, 56)")).toEqual({
      red: 12,
      green: 34,
      blue: 56,
      alpha: 1,
    });
    expect(parseCssColor("rgba(200, 100, 50, 0.25)")).toEqual({
      red: 200,
      green: 100,
      blue: 50,
      alpha: 0.25,
    });
    expect(parseCssColor("transparent")).toBeNull();
  });

  it("computes WCAG luminance for dark and light samples", () => {
    expect(relativeLuminance({ red: 0, green: 0, blue: 0 })).toBe(0);
    expect(relativeLuminance({ red: 255, green: 255, blue: 255 })).toBe(1);
    expect(relativeLuminance({ red: 127, green: 127, blue: 127 }))
      .toBeCloseTo(0.212, 2);
  });

  it("averages exactly nine context samples", () => {
    const samples = Array.from({ length: 9 }, (_, index) => ({
      red: index * 10,
      green: 90,
      blue: 180 - index * 10,
    }));

    expect(sampleNinePointAverage(samples)).toEqual({
      red: 40,
      green: 90,
      blue: 140,
    });
    expect(() => sampleNinePointAverage(samples.slice(0, 8))).toThrow(
      "nine",
    );
  });

  it("uses 0.42 and 0.58 hysteresis to avoid glyph flicker", () => {
    expect(resolveGlyphMode("light", 0.59)).toBe("dark");
    expect(resolveGlyphMode("dark", 0.57)).toBe("dark");
    expect(resolveGlyphMode("dark", 0.41)).toBe("light");
    expect(resolveGlyphMode("light", 0.43)).toBe("light");
  });
});
