import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";

const accessToken = "visual-baseline-access-token";
const sampleCount = 3;
const morphCycleCount = 10;
const maximumFcpMilliseconds = 1_200;
const maximumTransferredBytes = 250_000;
const maximumRequestCount = 15;
const maximumLongTaskMilliseconds = 65;
const maximumP95RafIntervalMilliseconds = 20;
const maximumSlowFrameRatio = 0.05;
const slowFrameThresholdMilliseconds = 25;

interface LoadMetrics {
  fcpMilliseconds: number;
  transferredBytes: number;
  requestCount: number;
  maximumLongTaskMilliseconds: number;
}

interface PerformanceProbe {
  rafRequested: number;
  rafExecuted: number;
  canvasDraws: number;
  frameTimestamps: number[];
  samplerFrameId: number | null;
  samplerRunning: boolean;
  longTasks: Array<{ duration: number; startTime: number }>;
}

interface IdleCounters {
  canvasDraws: number;
  rafExecuted: number;
  rafRequested: number;
}

function median(values: readonly number[]): number {
  const sortedValues = [...values].sort((left, right) => left - right);
  return sortedValues[Math.floor(sortedValues.length / 2)]!;
}

function percentile(
  values: readonly number[],
  percentileValue: number,
): number {
  const sortedValues = [...values].sort((left, right) => left - right);
  const index = Math.max(
    0,
    Math.ceil(sortedValues.length * percentileValue) - 1,
  );
  return sortedValues[index] ?? Number.POSITIVE_INFINITY;
}

async function installPerformanceProbe(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const probe: PerformanceProbe = {
      rafRequested: 0,
      rafExecuted: 0,
      canvasDraws: 0,
      frameTimestamps: [],
      samplerFrameId: null,
      samplerRunning: false,
      longTasks: [],
    };
    const instrumentedWindow = window as unknown as Window & {
      __liquidGlassV3Performance: PerformanceProbe;
    };
    instrumentedWindow.__liquidGlassV3Performance = probe;

    const nativeRequestAnimationFrame = window.requestAnimationFrame.bind(
      window,
    );
    window.requestAnimationFrame = (
      callback: FrameRequestCallback,
    ): number => {
      probe.rafRequested += 1;
      return nativeRequestAnimationFrame((timestamp) => {
        probe.rafExecuted += 1;
        callback(timestamp);
      });
    };

    const patchDrawMethods = (
      target: object | undefined,
      methodNames: readonly string[],
    ): void => {
      if (!target) return;
      const methods = target as Record<string, unknown>;
      for (const methodName of methodNames) {
        const originalMethod = methods[methodName];
        if (typeof originalMethod !== "function") continue;
        methods[methodName] = function instrumentedDraw(
          this: unknown,
          ...args: unknown[]
        ): unknown {
          probe.canvasDraws += 1;
          return Reflect.apply(originalMethod, this, args);
        };
      }
    };
    const constructors = globalThis as unknown as Record<
      string,
      { prototype: object } | undefined
    >;
    patchDrawMethods(constructors.CanvasRenderingContext2D?.prototype, [
      "clearRect",
      "drawImage",
      "fill",
      "fillRect",
      "putImageData",
      "stroke",
      "strokeRect",
    ]);
    patchDrawMethods(
      constructors.OffscreenCanvasRenderingContext2D?.prototype,
      [
        "clearRect",
        "drawImage",
        "fill",
        "fillRect",
        "putImageData",
        "stroke",
        "strokeRect",
      ],
    );
    patchDrawMethods(constructors.WebGLRenderingContext?.prototype, [
      "clear",
      "drawArrays",
      "drawElements",
    ]);
    patchDrawMethods(constructors.WebGL2RenderingContext?.prototype, [
      "clear",
      "drawArrays",
      "drawArraysInstanced",
      "drawElements",
      "drawElementsInstanced",
    ]);
    patchDrawMethods(constructors.GPUQueue?.prototype, ["submit"]);

    if ("PerformanceObserver" in window) {
      const observer = new PerformanceObserver((list) => {
        probe.longTasks.push(...list.getEntries().map((entry) => ({
          duration: entry.duration,
          startTime: entry.startTime,
        })));
      });
      try {
        observer.observe({ type: "longtask", buffered: true });
      } catch {
        observer.disconnect();
      }
    }
  });
}

async function openApp(page: Page, sampleIndex: number): Promise<void> {
  await page.goto(
    `/?liquid-glass-v3-performance=${sampleIndex}#${accessToken}`,
  );
  await expect(page.getByText("Đã kết nối", { exact: true })).toBeVisible();
  await expect(page.locator(".account-card")).toHaveCount(3);
}

test("keeps the OTP countdown live while bounding state requests", async ({
  page,
}) => {
  let stateRequests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/state") stateRequests += 1;
  });
  await openApp(page, 5);
  const otpCountdown = page.locator(".account-card").first().locator(".otp-validity");
  const initialText = await otpCountdown.textContent();

  await page.waitForTimeout(2_100);
  expect(await otpCountdown.textContent()).not.toBe(initialText);
  await page.waitForTimeout(4_000);

  expect(stateRequests).toBeGreaterThanOrEqual(1);
  expect(stateRequests).toBeLessThanOrEqual(2);
});

async function readLoadMetrics(page: Page): Promise<LoadMetrics> {
  return page.evaluate(() => {
    const navigation = performance.getEntriesByType(
      "navigation",
    )[0] as PerformanceNavigationTiming;
    const fcp = performance.getEntriesByType("paint").find(
      (entry) => entry.name === "first-contentful-paint",
    )?.startTime ?? Number.POSITIVE_INFINITY;
    const resources = performance.getEntriesByType(
      "resource",
    ) as PerformanceResourceTiming[];
    const probe = (
      window as unknown as {
        __liquidGlassV3Performance: PerformanceProbe;
      }
    ).__liquidGlassV3Performance;
    return {
      fcpMilliseconds: Number.isFinite(fcp)
        ? fcp
        : navigation.domContentLoadedEventEnd,
      transferredBytes: navigation.transferSize + resources.reduce(
        (total, resource) => total + resource.transferSize,
        0,
      ),
      requestCount: resources.length + 1,
      maximumLongTaskMilliseconds: Math.max(
        0,
        ...probe.longTasks.map((task) => task.duration),
      ),
    };
  });
}

async function startFrameSampler(page: Page): Promise<void> {
  await page.evaluate(() => {
    const probe = (
      window as unknown as {
        __liquidGlassV3Performance: PerformanceProbe;
      }
    ).__liquidGlassV3Performance;
    probe.frameTimestamps = [];
    probe.samplerRunning = true;
    const sampleFrame = (timestamp: number): void => {
      if (!probe.samplerRunning) return;
      probe.frameTimestamps.push(timestamp);
      probe.samplerFrameId = requestAnimationFrame(sampleFrame);
    };
    probe.samplerFrameId = requestAnimationFrame(sampleFrame);
  });
}

async function stopFrameSampler(page: Page): Promise<number[]> {
  return page.evaluate(() => {
    const probe = (
      window as unknown as {
        __liquidGlassV3Performance: PerformanceProbe;
      }
    ).__liquidGlassV3Performance;
    probe.samplerRunning = false;
    if (probe.samplerFrameId !== null) {
      cancelAnimationFrame(probe.samplerFrameId);
      probe.samplerFrameId = null;
    }
    return probe.frameTimestamps.slice(1).map(
      (timestamp, index) => timestamp - probe.frameTimestamps[index]!,
    );
  });
}

async function runMorphCycle(
  trigger: Locator,
  dialog: Locator,
  page: Page,
): Promise<void> {
  await trigger.click();
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("data-glass-version", "3");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(trigger).toBeFocused();
}

async function readIdleCounters(page: Page): Promise<IdleCounters> {
  return page.evaluate(() => {
    const probe = (
      window as unknown as {
        __liquidGlassV3Performance: PerformanceProbe;
      }
    ).__liquidGlassV3Performance;
    return {
      canvasDraws: probe.canvasDraws,
      rafExecuted: probe.rafExecuted,
      rafRequested: probe.rafRequested,
    };
  });
}

test.use({ viewport: { width: 1440, height: 1000 } });

test("keeps Liquid Glass v3 inside the production page budgets", async ({
  page,
}) => {
  await installPerformanceProbe(page);
  await openApp(page, 0);
  await page.goto("about:blank");
  const samples: LoadMetrics[] = [];
  for (let sampleIndex = 1; sampleIndex <= sampleCount; sampleIndex += 1) {
    await openApp(page, sampleIndex);
    await page.evaluate(() => new Promise<void>((resolveFrame) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolveFrame()));
    }));
    samples.push(await readLoadMetrics(page));
  }

  const medianMetrics = {
    fcpMilliseconds: median(
      samples.map((sample) => sample.fcpMilliseconds),
    ),
    transferredBytes: median(
      samples.map((sample) => sample.transferredBytes),
    ),
    requestCount: median(samples.map((sample) => sample.requestCount)),
  };
  const medianLongTask = median(
    samples.map((sample) => sample.maximumLongTaskMilliseconds),
  );

  console.info(`Liquid Glass v3 load samples: ${JSON.stringify(samples)}`);
  console.info(
    `Liquid Glass v3 load median: ${JSON.stringify(medianMetrics)}`,
  );
  expect(medianMetrics.fcpMilliseconds)
    .toBeLessThanOrEqual(maximumFcpMilliseconds);
  expect(medianMetrics.transferredBytes)
    .toBeLessThanOrEqual(maximumTransferredBytes);
  expect(medianMetrics.requestCount).toBeLessThanOrEqual(maximumRequestCount);
  expect(medianLongTask).toBeLessThanOrEqual(maximumLongTaskMilliseconds);
});

test("keeps ten v3 morph cycles smooth and stops all idle rendering", async ({
  page,
}) => {
  test.setTimeout(60_000);
  await installPerformanceProbe(page);
  await openApp(page, 1);

  const appearanceTrigger = page.getByRole("button", { name: "Giao diện" });
  const appearanceDialog = page.getByRole("dialog", {
    name: "Tùy chỉnh giao diện",
  });
  await expect.poll(async () => page.locator(
    '[data-glass-version="3"]:visible:not([data-glass-normal-map])',
  ).count()).toBe(0);
  await runMorphCycle(appearanceTrigger, appearanceDialog, page);
  await startFrameSampler(page);
  for (let cycleIndex = 0; cycleIndex < morphCycleCount; cycleIndex += 1) {
    await runMorphCycle(appearanceTrigger, appearanceDialog, page);
  }
  const frameIntervals = await stopFrameSampler(page);

  expect(frameIntervals.length).toBeGreaterThanOrEqual(morphCycleCount * 2);
  const p95RafInterval = percentile(frameIntervals, 0.95);
  const slowFrameCount = frameIntervals.filter(
    (interval) => interval > slowFrameThresholdMilliseconds,
  ).length;
  const slowFrameRatio = slowFrameCount / frameIntervals.length;
  console.info(`Liquid Glass v3 morph frames: ${JSON.stringify({
    frameCount: frameIntervals.length,
    p95RafInterval,
    slowFrameCount,
    slowFrameRatio,
  })}`);

  expect(p95RafInterval)
    .toBeLessThanOrEqual(maximumP95RafIntervalMilliseconds);
  expect(slowFrameRatio).toBeLessThanOrEqual(maximumSlowFrameRatio);

  await page.evaluate(() => new Promise<void>((resolveFrame) => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolveFrame()));
  }));
  await page.waitForTimeout(800);
  const settledCounters = await readIdleCounters(page);
  await page.waitForTimeout(250);
  const idleCounters = await readIdleCounters(page);
  expect(idleCounters).toEqual(settledCounters);
});

for (const effectsPreference of ["off", "full"] as const) {
  test(`keeps repeated workspace tab switches warm with effects ${effectsPreference}`, async ({
    page,
  }) => {
    test.setTimeout(60_000);
    await installPerformanceProbe(page);
    await page.addInitScript((preference) => {
      window.localStorage.setItem("otp-codex-effects", preference);
    }, effectsPreference);
    await openApp(page, effectsPreference === "off" ? 2 : 3);

    const accountsTab = page.getByRole("tab", { name: "Tài khoản" });
    const usageTab = page.getByRole("tab", { name: "Sử dụng" });
    const usageContent = page.locator(
      'section[aria-label="Sử dụng token"]',
    );

    await page.evaluate(() => performance.clearResourceTimings());
    await usageTab.click();
    await expect(usageContent).toBeVisible();
    await expect(page.locator(".heat-cell")).toHaveCount(365);
    await accountsTab.click();
    await expect(page.locator("#usage-panel")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    await expect(usageContent).toHaveCount(1);

    if (effectsPreference === "off") {
      const interactionResources = await page.evaluate(() => (
        performance.getEntriesByType("resource").map((entry) => entry.name)
      ));
      expect(
        interactionResources.some(
          (resource) => resource.includes("motionLite"),
        ),
      ).toBe(false);
    }

    await startFrameSampler(page);
    for (let cycleIndex = 0; cycleIndex < 10; cycleIndex += 1) {
      await usageTab.click();
      await expect(page.locator("#usage-panel")).toHaveAttribute(
        "aria-hidden",
        "false",
      );
      await accountsTab.click();
      await expect(page.locator("#usage-panel")).toHaveAttribute(
        "aria-hidden",
        "true",
      );
    }
    const frameIntervals = await stopFrameSampler(page);
    const p95RafInterval = percentile(frameIntervals, 0.95);
    const slowFrameCount = frameIntervals.filter(
      (interval) => interval > slowFrameThresholdMilliseconds,
    ).length;
    const slowFrameRatio = slowFrameCount / frameIntervals.length;
    console.info(`Workspace tab switch frames: ${JSON.stringify({
      effectsPreference,
      frameCount: frameIntervals.length,
      p95RafInterval,
      slowFrameCount,
      slowFrameRatio,
    })}`);

    expect(p95RafInterval)
      .toBeLessThanOrEqual(maximumP95RafIntervalMilliseconds);
    expect(slowFrameRatio).toBeLessThanOrEqual(maximumSlowFrameRatio);
  });
}

test("prewarms the selector morph runtime before its first click", async ({
  page,
}) => {
  await installPerformanceProbe(page);
  await page.addInitScript(() => {
    window.localStorage.setItem("otp-codex-effects", "full");
  });
  await openApp(page, 4);
  await page.evaluate(() => performance.clearResourceTimings());

  const trigger = page.getByRole("button", { name: /Lọc tài khoản/ });
  await trigger.hover();
  await expect.poll(() => page.evaluate(() => (
    performance.getEntriesByType("resource").some(
      (entry) => entry.name.includes("motionLite"),
    )
  ))).toBe(true);

  await startFrameSampler(page);
  await trigger.click();
  await expect(page.getByRole("dialog", {
    name: "Lọc tài khoản",
  })).toBeVisible();
  const frameIntervals = await stopFrameSampler(page);
  expect(percentile(frameIntervals, 0.95))
    .toBeLessThanOrEqual(maximumP95RafIntervalMilliseconds);
});
