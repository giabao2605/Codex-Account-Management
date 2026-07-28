import { expect, test } from "@playwright/test";
import type { Locator, Page } from "@playwright/test";

const accessToken = "visual-baseline-access-token";
const sceneIds = [
  "stripe",
  "checkerboard",
  "text",
  "white",
  "black",
  "color",
  "media",
] as const;
const temporalCheckpoints = [0, 40, 80, 140, 240, 400] as const;

async function openGlassLab(page: Page): Promise<Locator> {
  await page.goto(`/?glass-lab=1#${accessToken}`);
  const lab = page.getByTestId("glass-lab");
  await expect(lab).toBeVisible();
  return lab;
}

test.use({ viewport: { width: 1440, height: 1000 } });

test("publishes the v3 runtime and specimen contract", async ({ page }) => {
  const lab = await openGlassLab(page);
  const root = page.locator("html");

  await expect(lab).toHaveAttribute("data-glass-lab", "v3");
  await expect(root).toHaveAttribute("data-glass-quality", /full|reduced|off/);
  await expect(root).toHaveAttribute(
    "data-glass-motion",
    /full|reduced/,
  );
  await expect(root).toHaveAttribute(
    "data-glass-transparency",
    /normal|reduced/,
  );
  await expect(root).toHaveAttribute(
    "data-glass-contrast",
    /normal|increased|forced/,
  );
  await expect(lab.locator('[data-glass-version="3"]')).not.toHaveCount(0);

  for (const sceneId of sceneIds) {
    await expect(page.getByTestId(
      `glass-lab-background-${sceneId}`,
    )).toBeVisible();
    await expect(page.getByTestId(
      `glass-lab-${sceneId}-regular`,
    )).toHaveAttribute("data-glass-material", "regular");
  }
  await expect(page.getByTestId("glass-lab-media-clear")).toHaveAttribute(
    "data-glass-material",
    "clear",
  );
  await expect(lab.locator('[data-glass-material="clear"]')).toHaveCount(1);
});

test("exposes optical backgrounds beneath local refractive surfaces", async ({
  page,
}) => {
  await openGlassLab(page);

  for (const sceneId of ["stripe", "checkerboard", "text"] as const) {
    const scene = page.getByTestId(`glass-lab-background-${sceneId}`);
    const specimen = page.getByTestId(`glass-lab-${sceneId}-regular`);
    const [sceneBox, specimenBox] = await Promise.all([
      scene.boundingBox(),
      specimen.boundingBox(),
    ]);
    expect(sceneBox).not.toBeNull();
    expect(specimenBox).not.toBeNull();
    expect(specimenBox!.x).toBeGreaterThan(sceneBox!.x);
    expect(specimenBox!.y).toBeGreaterThan(sceneBox!.y);
    expect(specimenBox!.x + specimenBox!.width)
      .toBeLessThan(sceneBox!.x + sceneBox!.width);
    expect(specimenBox!.y + specimenBox!.height)
      .toBeLessThan(sceneBox!.y + sceneBox!.height);
    await expect(specimen).toHaveAttribute(
      "data-glass-normal-map",
      /.+/,
    );
    const material = await specimen.evaluate((element) => {
      const style = getComputedStyle(element, "::before");
      return {
        backdropFilter: style.backdropFilter,
        displacement: Number.parseFloat(
          style.getPropertyValue("--glass-displacement"),
        ),
      };
    });
    expect(material.backdropFilter).not.toBe("none");
    expect(material.displacement).toBeGreaterThanOrEqual(5);
    expect(material.displacement).toBeLessThanOrEqual(12);
    await expect(specimen).toHaveScreenshot(
      `glass-lab-${sceneId}-regular.png`,
      {
        animations: "disabled",
        maxDiffPixelRatio: 0.01,
      },
    );
  }
});

test("keeps accessibility axes independent", async ({ page }) => {
  await page.emulateMedia({
    reducedMotion: "reduce",
    forcedColors: "none",
  });
  await openGlassLab(page);
  const root = page.locator("html");

  await expect(root).toHaveAttribute("data-glass-motion", "reduced");
  await expect(root).toHaveAttribute("data-glass-transparency", "normal");
  await expect(root).toHaveAttribute("data-glass-contrast", "normal");
  await expect(page.getByTestId("glass-lab-morph-trigger")).toHaveAttribute(
    "aria-expanded",
    "false",
  );

  await page.emulateMedia({
    reducedMotion: "no-preference",
    forcedColors: "active",
  });
  await page.reload();
  await expect(page.getByTestId("glass-lab")).toBeVisible();
  await expect(root).toHaveAttribute("data-glass-quality", "off");
  await expect(root).toHaveAttribute("data-glass-contrast", "forced");
  await expect(page.getByTestId("glass-lab").locator("canvas")).toHaveCount(0);
});

test("opens and closes the shared morph with keyboard focus restoration", async ({
  page,
}) => {
  await openGlassLab(page);
  const trigger = page.getByTestId("glass-lab-morph-trigger");

  await trigger.focus();
  await page.keyboard.press("Enter");
  const destination = page.getByTestId("glass-lab-morph-destination");
  await expect(destination).toBeVisible();
  await expect(trigger).toHaveAttribute("aria-expanded", "true");
  const panel = destination.locator("xpath=ancestor::*[@role='dialog'][1]");
  await expect(panel).toHaveAttribute(
    "data-glass-morph-id",
    "glass-lab-morph",
  );
  await expect(panel.locator(":scope [data-glass-version='3']"))
    .toHaveCount(0);

  await page.keyboard.press("Escape");
  await expect(destination).toBeHidden();
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAttribute("aria-expanded", "false");
});

test("provides deterministic temporal checkpoints without snapshot updates", async ({
  page,
}) => {
  await page.clock.install({ time: new Date("2026-07-27T00:00:00Z") });
  await openGlassLab(page);
  const trigger = page.getByTestId("glass-lab-morph-trigger");
  await trigger.click();
  const destination = page.getByTestId("glass-lab-morph-destination");
  const panel = destination.locator("xpath=ancestor::*[@role='dialog'][1]");
  let elapsed = 0;

  for (const checkpoint of temporalCheckpoints) {
    await page.clock.runFor(checkpoint - elapsed);
    elapsed = checkpoint;
    await expect(panel).toBeVisible();
    const frame = await panel.evaluate((element) => {
      const box = element.getBoundingClientRect();
      const style = getComputedStyle(element);
      return {
        width: box.width,
        height: box.height,
        opacity: Number.parseFloat(style.opacity || "1"),
      };
    });
    expect(Number.isFinite(frame.width)).toBe(true);
    expect(Number.isFinite(frame.height)).toBe(true);
    expect(Number.isFinite(frame.opacity)).toBe(true);
    expect(frame.width).toBeGreaterThan(0);
    expect(frame.height).toBeGreaterThan(0);
    expect(frame.opacity).toBeGreaterThanOrEqual(0);
    expect(frame.opacity).toBeLessThanOrEqual(1);
    await expect(panel).toHaveScreenshot(
      `glass-lab-morph-${checkpoint}ms.png`,
      {
        animations: "allow",
        maxDiffPixelRatio: 0.02,
      },
    );
  }

  await expect(destination).toBeVisible();
  await expect(panel).toHaveAttribute("data-glass-morph-state", "settled");
});
