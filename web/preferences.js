(function exposeDashboardPreferences(root) {
  "use strict";

  const STORAGE_KEY = "aoa-dashboard.preferences.v1";
  const LEGACY_LANGUAGE_KEY = "aoa-dashboard.language";
  const LEGACY_THEME_KEY = "aoa-dashboard-theme-mode";
  const VERSION = 1;
  const MODES = ["system", "light", "dark"];
  const DENSITIES = ["comfortable", "compact"];

  function safeStorage(store) {
    return store && typeof store.getItem === "function" && typeof store.setItem === "function" ? store : null;
  }

  function normalizeLanguage(value) {
    const normalized = String(value || "").trim().toLowerCase();
    if (normalized.startsWith("ru")) return "ru";
    if (normalized.startsWith("en")) return "en";
    return null;
  }

  function normalizeTheme(value) {
    return MODES.includes(value) ? value : null;
  }

  function defaults() {
    return { version: VERSION, language: null, theme: "system", density: "comfortable" };
  }

  function read(store) {
    const storage = safeStorage(store);
    const fallback = defaults();
    if (!storage) return fallback;

    let raw = null;
    try {
      raw = storage.getItem(STORAGE_KEY);
    } catch (_error) {
      return fallback;
    }

    if (raw !== null && raw !== "") {
      try {
        const parsed = JSON.parse(raw);
        if (!parsed || typeof parsed !== "object" || parsed.version !== VERSION) return fallback;
        return {
          version: VERSION,
          language: normalizeLanguage(parsed.language),
          theme: normalizeTheme(parsed.theme) || "system",
          density: DENSITIES.includes(parsed.density) ? parsed.density : "comfortable",
        };
      } catch (_error) {
        // A present but malformed/future record is invalid, not a migration cue.
        return fallback;
      }
    }

    try {
      return {
        version: VERSION,
        language: normalizeLanguage(storage.getItem(LEGACY_LANGUAGE_KEY)),
        theme: normalizeTheme(storage.getItem(LEGACY_THEME_KEY)) || "system",
        density: "comfortable",
      };
    } catch (_error) {
      return fallback;
    }
  }

  function write(store, updates = {}) {
    const storage = safeStorage(store);
    const current = read(storage);
    const next = {
      version: VERSION,
      language: normalizeLanguage(updates.language) || current.language || "en",
      theme: normalizeTheme(updates.theme) || current.theme || "system",
      density: DENSITIES.includes(updates.density) ? updates.density : current.density,
    };
    if (storage) {
      try { storage.setItem(STORAGE_KEY, JSON.stringify(next)); } catch (_error) { /* best effort */ }
    }
    return next;
  }

  root.AoaDashboardPreferences = Object.freeze({
    storageKey: STORAGE_KEY,
    legacyLanguageKey: LEGACY_LANGUAGE_KEY,
    legacyThemeKey: LEGACY_THEME_KEY,
    version: VERSION,
    modes: MODES.slice(),
    densities: DENSITIES.slice(),
    normalizeLanguage,
    normalizeTheme,
    read,
    write,
  });
}(typeof window === "undefined" ? globalThis : window));
