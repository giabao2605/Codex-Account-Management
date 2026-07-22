"use strict";

(() => {
  const themeStorageKey = "otp-codex-theme";
  let storedTheme = "";

  try {
    storedTheme = window.localStorage.getItem(themeStorageKey) || "";
  } catch (_error) {
    storedTheme = "";
  }

  const prefersLight = window.matchMedia?.("(prefers-color-scheme: light)").matches;
  const theme = ["light", "dark"].includes(storedTheme)
    ? storedTheme
    : (prefersLight ? "light" : "dark");

  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  document.querySelector("#theme-color").content = theme === "light"
    ? "#f3f6fc"
    : "#0b1020";
})();
