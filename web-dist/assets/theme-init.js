"use strict";

(() => {
  let preference;
  let effects;

  try {
    preference = window.localStorage.getItem("otp-codex-theme-preference")
      || window.localStorage.getItem("otp-codex-theme")
      || "system";
    effects = window.localStorage.getItem("otp-codex-effects") || "auto";
  } catch {
    preference = "system";
    effects = "auto";
  }

  const prefersLight = window.matchMedia?.("(prefers-color-scheme: light)").matches;
  const theme = ["light", "dark"].includes(preference)
    ? preference
    : (prefersLight ? "light" : "dark");

  document.documentElement.dataset.theme = theme;
  document.documentElement.dataset.effects = effects === "off"
    ? "off"
    : "reduced";
  document.documentElement.style.colorScheme = theme;
  document.querySelector("#theme-color").content = theme === "light"
    ? "#dfe4eb"
    : "#090d15";
})();
