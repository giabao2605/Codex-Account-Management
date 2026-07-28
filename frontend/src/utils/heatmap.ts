import type { TokenUsageDailyBucket } from "@/types/api.ts";

export type HeatmapMode = "daily" | "weekly" | "cumulative";

export interface HeatmapCell {
  startDate: string;
  endDate: string;
  tokens: number;
  column: number;
  row: number;
}

export interface HeatmapMonthLabel {
  key: string;
  label: string;
  column: number;
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;
const DAY_MILLISECONDS = 86_400_000;

function parseIsoDate(value: string): Date {
  return new Date(`${value}T00:00:00Z`);
}

function isIsoDate(value: string): boolean {
  if (!ISO_DATE.test(value)) return false;
  return isoDate(parseIsoDate(value)) === value;
}

function isoDate(value: Date): string {
  return value.toISOString().slice(0, 10);
}

function localIsoDate(value: Date): string {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function addDays(value: string, days: number): string {
  const date = parseIsoDate(value);
  date.setUTCDate(date.getUTCDate() + days);
  return isoDate(date);
}

function dayDifference(start: string, end: string): number {
  return Math.round(
    (parseIsoDate(end).getTime() - parseIsoDate(start).getTime())
    / DAY_MILLISECONDS,
  );
}

function mondayOf(value: string): string {
  const date = parseIsoDate(value);
  const offset = (date.getUTCDay() + 6) % 7;
  date.setUTCDate(date.getUTCDate() - offset);
  return isoDate(date);
}

function startOfTrailingYear(endDate: string): string {
  const end = parseIsoDate(endDate);
  const priorYear = end.getUTCFullYear() - 1;
  const month = end.getUTCMonth();
  const day = end.getUTCDate();
  const finalDay = new Date(Date.UTC(priorYear, month + 1, 0)).getUTCDate();
  return addDays(
    isoDate(new Date(Date.UTC(priorYear, month, Math.min(day, finalDay)))),
    1,
  );
}

function tokenMap(
  buckets: readonly TokenUsageDailyBucket[],
  startDate: string,
  endDate: string,
): ReadonlyMap<string, number> {
  const values = new Map<string, number>();
  for (const bucket of buckets) {
    if (
      !isIsoDate(bucket.start_date)
      || bucket.start_date < startDate
      || bucket.start_date > endDate
      || !Number.isFinite(bucket.tokens)
      || bucket.tokens < 0
    ) {
      continue;
    }
    values.set(
      bucket.start_date,
      (values.get(bucket.start_date) ?? 0) + Math.round(bucket.tokens),
    );
  }
  return values;
}

export function resolveHeatmapEndDate(
  generatedAt: string | null | undefined,
  buckets: readonly TokenUsageDailyBucket[] | null,
  now = new Date(),
): string {
  const generatedDate = generatedAt?.slice(0, 10) ?? "";
  if (isIsoDate(generatedDate)) return generatedDate;
  const latestBucket = (buckets ?? [])
    .map((bucket) => bucket.start_date)
    .filter(isIsoDate)
    .sort((left, right) => right.localeCompare(left))[0];
  return latestBucket ?? localIsoDate(now);
}

export function buildHeatmapCells(
  buckets: readonly TokenUsageDailyBucket[] | null,
  mode: HeatmapMode,
  endDate: string,
): HeatmapCell[] | null {
  if (buckets === null) return null;
  if (!isIsoDate(endDate)) {
    throw new Error("Heatmap end date must use YYYY-MM-DD.");
  }

  const startDate = startOfTrailingYear(endDate);
  const values = tokenMap(buckets, startDate, endDate);
  const gridStart = mondayOf(startDate);
  if (mode === "daily") {
    return Array.from(
      { length: dayDifference(startDate, endDate) + 1 },
      (_, index): HeatmapCell => {
        const date = addDays(startDate, index);
        const parsed = parseIsoDate(date);
        return {
          startDate: date,
          endDate: date,
          tokens: values.get(date) ?? 0,
          column: Math.floor(dayDifference(gridStart, date) / 7) + 1,
          row: ((parsed.getUTCDay() + 6) % 7) + 1,
        };
      },
    );
  }

  const weeklyValues = new Map<string, number>();
  for (let date = startDate; date <= endDate; date = addDays(date, 1)) {
    const week = mondayOf(date);
    weeklyValues.set(week, (weeklyValues.get(week) ?? 0) + (values.get(date) ?? 0));
  }
  const weeklyCells = [...weeklyValues.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([weekStart, tokens]) => ({
      startDate: weekStart < startDate ? startDate : weekStart,
      endDate: addDays(weekStart, 6) > endDate ? endDate : addDays(weekStart, 6),
      tokens,
    }));
  const compactCells = weeklyCells.length <= 53
    ? weeklyCells
    : [
        {
          startDate: weeklyCells[0]?.startDate ?? startDate,
          endDate: weeklyCells[1]?.endDate ?? startDate,
          tokens:
            (weeklyCells[0]?.tokens ?? 0)
            + (weeklyCells[1]?.tokens ?? 0),
        },
        ...weeklyCells.slice(2),
      ];
  let cumulative = 0;
  return compactCells.map((cell, index): HeatmapCell => {
    const { startDate: cellStart, endDate: cellEnd, tokens } = cell;
    cumulative += tokens;
    return {
      startDate: cellStart,
      endDate: cellEnd,
      tokens: mode === "cumulative" ? cumulative : tokens,
      column: index + 1,
      row: 1,
    };
  });
}

export function buildHeatmapMonthLabels(
  cells: readonly HeatmapCell[],
): HeatmapMonthLabel[] {
  const labels: HeatmapMonthLabel[] = [];
  let previousKey = "";
  for (const cell of cells) {
    const key = cell.startDate.slice(0, 7);
    if (key === previousKey) continue;
    previousKey = key;
    const month = Number(key.slice(5, 7));
    labels.push({
      key,
      label: `T${month}`,
      column: cell.column,
    });
  }
  return labels;
}

export function heatmapLevel(tokens: number, maximum: number): number {
  if (tokens <= 0 || maximum <= 0) return 0;
  return Math.max(1, Math.min(4, Math.ceil((tokens / maximum) * 4)));
}
