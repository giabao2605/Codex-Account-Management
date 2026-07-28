import { createPinia, setActivePinia } from "pinia";
import { mount } from "@vue/test-utils";
import { beforeEach, describe, expect, it } from "vitest";

import { useFeedbackStore } from "@/stores/feedback.ts";
import FeedbackToast from "./FeedbackToast.vue";

describe("FeedbackToast", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("renders success and error feedback with the matching live role", async () => {
    const feedback = useFeedbackStore();
    const wrapper = mount(FeedbackToast);

    feedback.success("Đã hoàn tất.");
    await wrapper.vm.$nextTick();
    expect(wrapper.get(".feedback-toast").attributes("role")).toBe("status");
    expect(wrapper.text()).toContain("Đã hoàn tất.");

    feedback.error("Không thể hoàn tất.");
    await wrapper.vm.$nextTick();
    expect(wrapper.get(".feedback-toast").attributes("role")).toBe("alert");
    expect(wrapper.text()).toContain("Không thể hoàn tất.");
  });
});
