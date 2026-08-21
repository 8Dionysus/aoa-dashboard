(function installTheme(global) {
  "use strict";

  var document = global.document;
  if (!document || !document.documentElement) {
    return;
  }

  var root = document.documentElement;
  var storageKey = "aoa-dashboard-theme-mode";
  var modes = ["system", "light", "dark"];
  var labels = { system: "System", light: "Light", dark: "Dark" };
  var currentMode = "system";
  var mediaQuery = null;
  var control = null;

  function isMode(value) {
    return modes.indexOf(value) !== -1;
  }

  function readStoredMode() {
    try {
      var stored = global.localStorage.getItem(storageKey);
      return isMode(stored) ? stored : "system";
    } catch (error) {
      return "system";
    }
  }

  function prefersDark() {
    if (mediaQuery) {
      return Boolean(mediaQuery.matches);
    }
    try {
      return Boolean(global.matchMedia && global.matchMedia("(prefers-color-scheme: dark)").matches);
    } catch (error) {
      return false;
    }
  }

  function resolvedMode(mode) {
    return mode === "system" ? (prefersDark() ? "dark" : "light") : mode;
  }

  function persistMode(mode) {
    try {
      global.localStorage.setItem(storageKey, mode);
    } catch (error) {
      // Private browsing and embedded WebViews may make storage unavailable.
    }
  }

  function updateControl() {
    if (!control) {
      return;
    }
    control.select.value = currentMode;
    control.select.setAttribute("aria-label", "Color theme: " + labels[currentMode]);
  }

  function applyMode(mode, persist) {
    currentMode = isMode(mode) ? mode : "system";
    root.dataset.themeMode = currentMode;
    root.dataset.theme = resolvedMode(currentMode);
    if (persist) {
      persistMode(currentMode);
    }
    updateControl();
  }

  function handleSystemChange() {
    if (currentMode === "system") {
      applyMode(currentMode, false);
    }
  }

  function bindSystemPreference() {
    if (!global.matchMedia) {
      return;
    }
    try {
      mediaQuery = global.matchMedia("(prefers-color-scheme: dark)");
      if (typeof mediaQuery.addEventListener === "function") {
        mediaQuery.addEventListener("change", handleSystemChange);
      } else if (typeof mediaQuery.addListener === "function") {
        mediaQuery.addListener(handleSystemChange);
      }
    } catch (error) {
      mediaQuery = null;
    }
  }

  function makeControl() {
    var host = document.querySelector(".mast-meta");
    if (!host || host.querySelector("[data-theme-control]")) {
      return;
    }

    var fieldset = document.createElement("fieldset");
    fieldset.className = "theme-control";
    fieldset.dataset.themeControl = "true";

    var legend = document.createElement("legend");
    legend.className = "theme-control-label";
    legend.textContent = "Theme";

    var select = document.createElement("select");
    select.id = "theme-mode";
    select.name = "theme-mode";
    select.setAttribute("aria-label", "Color theme");
    modes.forEach(function (mode) {
      var option = document.createElement("option");
      option.value = mode;
      option.textContent = labels[mode];
      select.append(option);
    });
    select.addEventListener("change", function () {
      applyMode(select.value, true);
    });

    fieldset.append(legend, select);
    host.append(fieldset);
    control = { fieldset: fieldset, select: select };
    updateControl();
  }

  function start() {
    applyMode(readStoredMode(), false);
    bindSystemPreference();
    makeControl();
  }

  global.AoaDashboardTheme = {
    modes: modes.slice(),
    storageKey: storageKey,
    getMode: function () { return currentMode; },
    setMode: function (mode) {
      applyMode(mode, true);
      return currentMode;
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
}(window));
