(function installTheme(global) {
  "use strict";

  var document = global.document;
  if (!document || !document.documentElement) {
    return;
  }

  var root = document.documentElement;
  var preferenceApi = global.AoaDashboardPreferences || null;
  var readPresentationPreferences = preferenceApi && preferenceApi.read;
  var writePresentationPreferences = preferenceApi && preferenceApi.write;
  var storageKey = preferenceApi && preferenceApi.legacyThemeKey || "aoa-dashboard-theme-mode";
  var preferenceStorageKey = preferenceApi && preferenceApi.storageKey || "aoa-dashboard.preferences.v1";
  var modes = ["system", "light", "dark"];
  var densities = ["comfortable", "compact"];
  var labels = {
    label: "Theme",
    ariaLabel: "Color theme",
    system: "System",
    light: "Light",
    dark: "Dark"
  };
  var currentMode = "system";
  var currentDensity = "comfortable";
  var mediaQuery = null;
  var control = null;
  var listeners = [];

  function isMode(value) {
    return modes.indexOf(value) !== -1;
  }

  function readStoredMode() {
    if (readPresentationPreferences) {
      try {
        var versioned = readPresentationPreferences(global.localStorage);
        return versioned && isMode(versioned.theme) ? versioned.theme : "system";
      } catch (error) {
        return "system";
      }
    }
    try {
      var preferences = null;
      if (preferences && isMode(preferences.theme)) return preferences.theme;
    } catch (error) {
      // Fall through to the legacy key and safe defaults.
    }
    try {
      var stored = global.localStorage.getItem(storageKey);
      return isMode(stored) ? stored : "system";
    } catch (error) {
      return "system";
    }
  }

  function readStoredDensity() {
    if (readPresentationPreferences) {
      try {
        var versioned = readPresentationPreferences(global.localStorage);
        return versioned && densities.indexOf(versioned.density) !== -1 ? versioned.density : "comfortable";
      } catch (error) {
        return "comfortable";
      }
    }
    try {
      var preferences = null;
      return preferences && densities.indexOf(preferences.density) !== -1 ? preferences.density : "comfortable";
    } catch (error) {
      return "comfortable";
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
      if (writePresentationPreferences) {
        writePresentationPreferences(global.localStorage, { theme: mode, density: currentDensity });
      }
    } catch (error) {
      // The legacy key below is also best-effort.
    }
    try {
      global.localStorage.setItem(storageKey, mode);
    } catch (error) {
      // Private browsing and embedded WebViews may make storage unavailable.
    }
  }

  function persistDensity(density) {
    try {
      if (writePresentationPreferences) {
        writePresentationPreferences(global.localStorage, { theme: currentMode, density: density });
      }
    } catch (error) {
      // Embedded WebViews may not expose writable storage.
    }
  }

  function updateControl() {
    if (!control) {
      return;
    }
    control.select.value = currentMode;
    control.legend.textContent = labels.label;
    control.select.setAttribute("aria-label", labels.ariaLabel + ": " + labels[currentMode]);
    var options = control.select.options || control.select.children || [];
    Array.prototype.forEach.call(options, function (option) {
      option.textContent = labels[option.value];
    });
  }

  function setLabels(nextLabels) {
    if (!nextLabels || typeof nextLabels !== "object") {
      return;
    }
    ["label", "ariaLabel", "system", "light", "dark"].forEach(function (key) {
      if (typeof nextLabels[key] === "string" && nextLabels[key]) {
        labels[key] = nextLabels[key];
      }
    });
    updateControl();
  }

  function applyMode(mode, persist) {
    var previousMode = currentMode;
    var previousResolved = root.dataset.theme;
    currentMode = isMode(mode) ? mode : "system";
    root.dataset.themeMode = currentMode;
    root.dataset.theme = resolvedMode(currentMode);
    root.dataset.density = currentDensity;
    if (persist) {
      persistMode(currentMode);
    }
    updateControl();
    if (previousMode !== currentMode || previousResolved !== root.dataset.theme) {
      listeners.slice().forEach(function (listener) {
        listener(currentMode, root.dataset.theme);
      });
    }
  }

  function applyDensity(density, persist) {
    currentDensity = densities.indexOf(density) !== -1 ? density : "comfortable";
    root.dataset.density = currentDensity;
    if (persist) persistDensity(currentDensity);
    listeners.slice().forEach(function (listener) {
      listener(currentMode, root.dataset.theme, currentDensity);
    });
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
    if (!host) {
      return;
    }
    var existing = host.querySelector("[data-theme-control]");
    if (existing) {
      control = { fieldset: existing, legend: existing.children[0], select: existing.children[1] };
      updateControl();
      return;
    }

    var fieldset = document.createElement("fieldset");
    fieldset.className = "theme-control";
    fieldset.dataset.themeControl = "true";

    var legend = document.createElement("legend");
    legend.className = "theme-control-label";
    legend.textContent = labels.label;

    var select = document.createElement("select");
    select.id = "theme-mode";
    select.name = "theme-mode";
    select.setAttribute("aria-label", labels.ariaLabel);
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
    control = { fieldset: fieldset, legend: legend, select: select };
    updateControl();
  }

  function start() {
    currentDensity = readStoredDensity();
    applyMode(readStoredMode(), false);
    bindSystemPreference();
    makeControl();
  }

  global.AoaDashboardTheme = {
    modes: modes.slice(),
    storageKey: storageKey,
    preferenceStorageKey: preferenceStorageKey,
    densities: densities.slice(),
    getMode: function () { return currentMode; },
    getDensity: function () { return currentDensity; },
    subscribe: function (listener) {
      if (typeof listener !== "function") {
        return function () {};
      }
      listeners.push(listener);
      return function () {
        listeners = listeners.filter(function (candidate) { return candidate !== listener; });
      };
    },
    setLabels: setLabels,
    setMode: function (mode) {
      applyMode(mode, true);
      return currentMode;
    },
    setDensity: function (density) {
      applyDensity(density, true);
      return currentDensity;
    }
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
}(window));
