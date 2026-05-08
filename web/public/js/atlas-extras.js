/* MetroNow Atlas — display tweaks (theme, density, accent, weight) with persistence.
   Reads <script id="default-tweaks"> for defaults, then localStorage overrides. */
(function () {
  "use strict";

  const KEY = "metronow.tweaks";

  function loadDefaults() {
    try {
      const el = document.getElementById("default-tweaks");
      if (!el) return {};
      const txt = el.textContent
        .replace(/\/\*EDITMODE-BEGIN\*\//g, "")
        .replace(/\/\*EDITMODE-END\*\//g, "")
        .trim();
      return JSON.parse(txt);
    } catch { return {}; }
  }

  function load() {
    const def = { theme: "auto", density: "comfortable", accent: "orange", weight: "med", ...loadDefaults() };
    try {
      const saved = JSON.parse(localStorage.getItem(KEY) || "null");
      if (saved && typeof saved === "object") return { ...def, ...saved };
    } catch {}
    return def;
  }

  function save(t) { localStorage.setItem(KEY, JSON.stringify(t)); }

  function effectiveTheme(theme) {
    if (theme !== "auto") return theme;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }

  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", effectiveTheme(t.theme));
    document.documentElement.setAttribute("data-density", t.density);
    document.documentElement.setAttribute("data-accent", t.accent);
    document.documentElement.setAttribute("data-weight", t.weight);
    window.atlasWeight = t.weight;
    // sync segmented controls + swatches
    syncSeg("theme", t.theme);
    syncSeg("density", t.density);
    syncSeg("weight", t.weight);
    syncSwatch("accent", t.accent);
    // theme button icon swap (sun/moon) is purely decorative in the source HTML; toggle via theme attr
  }

  function syncSeg(name, value) {
    document.querySelectorAll(`.seg[data-tweak="${name}"] .seg-btn`).forEach((b) => {
      b.setAttribute("aria-pressed", b.dataset.v === value ? "true" : "false");
    });
  }
  function syncSwatch(name, value) {
    document.querySelectorAll(`.tweak-swatches[data-tweak="${name}"] .tweak-swatch`).forEach((b) => {
      b.setAttribute("aria-pressed", b.dataset.v === value ? "true" : "false");
    });
  }

  function wire() {
    const state = load();
    applyTheme(state);

    // segmented controls
    document.querySelectorAll(".seg").forEach((seg) => {
      const name = seg.dataset.tweak;
      seg.querySelectorAll(".seg-btn").forEach((btn) => {
        btn.addEventListener("click", () => {
          state[name] = btn.dataset.v;
          save(state);
          applyTheme(state);
          if (name === "weight" && typeof window.atlasRedraw === "function") window.atlasRedraw();
        });
      });
    });
    // swatches
    document.querySelectorAll(".tweak-swatches").forEach((wrap) => {
      const name = wrap.dataset.tweak;
      wrap.querySelectorAll(".tweak-swatch").forEach((btn) => {
        btn.addEventListener("click", () => {
          state[name] = btn.dataset.v;
          save(state);
          applyTheme(state);
        });
      });
    });

    // header buttons
    const tweaksBtn = document.getElementById("tweaksBtn");
    const tweaksPanel = document.getElementById("tweaksPanel");
    const tweaksClose = document.getElementById("tweaksClose");
    if (tweaksBtn && tweaksPanel) {
      tweaksBtn.addEventListener("click", () => tweaksPanel.classList.toggle("open"));
    }
    if (tweaksClose && tweaksPanel) {
      tweaksClose.addEventListener("click", () => tweaksPanel.classList.remove("open"));
    }
    document.addEventListener("click", (e) => {
      if (!tweaksPanel || !tweaksPanel.classList.contains("open")) return;
      if (tweaksPanel.contains(e.target) || (tweaksBtn && tweaksBtn.contains(e.target))) return;
      tweaksPanel.classList.remove("open");
    });

    // Theme button cycles through light → dark → auto so the segmented
    // control's "Auto" state stays reachable from the header chip.
    const themeBtn = document.getElementById("themeBtn");
    if (themeBtn) {
      themeBtn.addEventListener("click", () => {
        const order = ["light", "dark", "auto"];
        const cur = state.theme;
        const next = order[(order.indexOf(cur) + 1) % order.length] || "light";
        state.theme = next;
        save(state);
        applyTheme(state);
      });
    }

    // react to OS theme changes when in auto mode
    if (window.matchMedia) {
      window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
        if (state.theme === "auto") applyTheme(state);
      });
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", wire);
  } else {
    wire();
  }
})();
