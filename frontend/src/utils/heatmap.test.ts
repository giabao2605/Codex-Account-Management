import { describe, expect, it } from "vitest";

import type { TokenUsageDailyBucket } from "@/types/api.ts";
import {
  buildHeatmapMonthLabels,
  buildHeatmapCells,
  heatmapLevel,
  resolveHeatmapEndDate,
} from "./heatmap.ts";

const buckets: TokenUsageDailyBucket[] = [
  { start_date: "2026-07-20", tokens: 100 },
  { start_date: "2026-07-21", tokens: 200 },
  { start_date: "2026-07-22", tokens: 300 },
  { start_date: "2026-07-23", tokens: 400 },
];

describe("heatmap parity utilities", () => {
  it("preserves daily values and aggregates weekly and cumulative modes", () => {
    const daily = buildHeatmapCells(buckets, "daily", "2026-07-23");
    const weekly = buildHeatmapCells(buckets, "weekly", "2026-07-23");
    const cumulative = buildHeatmapCells(buckets, "cumulative", "2026-07-23");
    if (!daily || !weekly || !cumulative) {
      throw new Error("Expected available heatmap cells");
    }

    expect(daily).toHaveLength(365);
    expect(daily.slice(-4).map((cell) => cell.tokens)).toEqual([100, 200, 300, 400]);
    expect([52, 53]).toContain(weekly.length);
    expect(weekly.at(-1)?.tokens).toBe(1_000);
    expect(cumulative.at(-1)?.tokens).toBe(1_000);
  });

  it("distinguishes unavailable buckets from an available zero grid", () => {
    expect(buildHeatmapCells(null, "daily", "2026-07-23")).toBeNull();
    const empty = buildHeatmapCells([], "daily", "2026-07-23");
    expect(empty).toHaveLength(365);
    expect(empty?.every((cell) => cell.tokens === 0)).toBe(true);
    expect(heatmapLevel(0, 400)).toBe(0);
    expect(heatmapLevel(400, 400)).toBe(4);
    expect(heatmapLevel(100, 400)).toBe(1);
  });

  it("uses generated time, then latest bucket, then local date for the range end", () => {
    expect(resolveHeatmapEndDate("2026-07-23T09:45:00+07:00", buckets)).toBe(
      "2026-07-23",
    );
    expect(resolveHeatmapEndDate("invalid", buckets)).toBe("2026-07-23");
    expect(resolveHeatmapEndDate("", [], new Date(2025, 0, 2, 23, 30))).toBe(
      "2025-01-02",
    );
  });

  it("covers leap years and emits compact Vietnamese month labels", () => {
    const leap = buildHeatmapCells([], "daily", "2024-02-29");
    expect(leap).toHaveLength(366);
    const labels = buildHeatmapMonthLabels(leap ?? []);
    expect(labels).toHaveLength(12);
    expect(labels.map((label) => label.label)).toContain("T2");
    expect(labels.every((label) => label.column > 0)).toBe(true);
  });

  it("keeps boundary-heavy weekly ranges within 53 cells without losing tokens", () => {
    const edgeBuckets = [
      { start_date: "2024-01-07", tokens: 10 },
      { start_date: "2025-01-06", tokens: 20 },
    ];
    const weekly = buildHeatmapCells(edgeBuckets, "weekly", "2025-01-06");
    const cumulative = buildHeatmapCells(edgeBuckets, "cumulative", "2025-01-06");

    expect(weekly?.length).toBeLessThanOrEqual(53);
    expect(weekly?.reduce((sum, cell) => sum + cell.tokens, 0)).toBe(30);
    expect(cumulative?.at(-1)?.tokens).toBe(30);
  });
});
