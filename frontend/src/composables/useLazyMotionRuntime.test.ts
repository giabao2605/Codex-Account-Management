import { mount } from "@vue/test-utils";
import { defineComponent, h } from "vue";
import { describe, expect, it } from "vitest";

import { useLazyMotionRuntime } from "./useLazyMotionRuntime";

function mountRuntimeProbe() {
  let runtime!: ReturnType<typeof useLazyMotionRuntime>;
  const Probe = defineComponent({
    setup() {
      runtime = useLazyMotionRuntime();
      return () => h(runtime.motionDiv.value, { "data-motion-probe": "" });
    },
  });

  return {
    runtime: () => runtime,
    wrapper: mount(Probe),
  };
}

describe("useLazyMotionRuntime", () => {
  it("preloads without replacing semantic fallbacks", async () => {
    const probe = mountRuntimeProbe();

    await probe.runtime().preloadMotion();

    expect(probe.runtime().ready.value).toBe(false);
    expect(probe.runtime().motionDiv.value).toBe("div");

    await probe.runtime().ensureMotion();
    expect(probe.runtime().ready.value).toBe(true);
    probe.wrapper.unmount();
  });

  it("starts with semantic fallbacks and resolves one shared runtime", async () => {
    const probe = mountRuntimeProbe();

    expect(probe.runtime().ready.value).toBe(false);
    expect(probe.runtime().layoutGroup.value).toBe("div");
    expect(probe.runtime().motionDiv.value).toBe("div");
    expect(probe.runtime().motionSpan.value).toBe("span");
    expect(probe.runtime().presence.value).toBe("div");

    await probe.runtime().ensureMotion();
    expect(probe.runtime().ready.value).toBe(true);
    expect(probe.runtime().layoutGroup.value).not.toBe("div");
    expect(probe.runtime().motionDiv.value).not.toBe("div");
    expect(probe.runtime().motionSpan.value).not.toBe("span");
    expect(probe.runtime().presence.value).not.toBe("div");

    await probe.runtime().ensureMotion();
    expect(probe.runtime().ready.value).toBe(true);
    probe.wrapper.unmount();
  });

  it("does not install a runtime after its consumer unmounts", async () => {
    const probe = mountRuntimeProbe();
    const loading = probe.runtime().ensureMotion();
    probe.wrapper.unmount();

    await loading;
    expect(probe.runtime().ready.value).toBe(false);
  });
});
