import { create } from "zustand";

const KEY = "sceneform.prefs";

function loadPrefs() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "{}");
  } catch {
    return {};
  }
}

function savePrefs(p) {
  try {
    localStorage.setItem(KEY, JSON.stringify(p));
  } catch {
    /* storage unavailable (private mode) — preferences just won't persist */
  }
}

const prefs = loadPrefs();

export function applyTheme(theme) {
  const dark = theme === "dark" || (theme === "system" && matchMedia("(prefers-color-scheme: dark)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  try {
    localStorage.setItem("sceneform.theme", theme);
  } catch {
    /* ignore */
  }
}

export const DEFAULT_VIEW = {
  layer: "points", // points | splat | mesh
  pointSet: "dense", // dense | sparse
  colorMode: "rgb", // rgb | white | confidence | depth | density
  pointSize: 1.6,
  confidence: 0.5,
  exposure: 1,
  showCameras: true,
  showPath: false,
  showGrid: true,
  showAxes: true,
  showBounds: false,
  projection: "perspective",
  background: "studio", // studio | dark | light
};

export const useStore = create((set, get) => ({
  theme: prefs.theme || "system",
  expertise: prefs.expertise || "beginner",
  renderQuality: prefs.renderQuality || "balanced",
  apiOverride: prefs.apiOverride || "",
  view: { ...DEFAULT_VIEW },
  tool: "orbit", // orbit | fly | measure
  selectedCamera: null,
  measurePoints: [],
  hoverPoint: null,
  replaying: false,
  compare: null, // { mode: 'split'|'overlay'|'original'|'reconstruction'|'difference', opacity, split }
  inspector: "overview",
  sheetOpen: false,

  setPref(key, value) {
    set({ [key]: value });
    const s = get();
    savePrefs({ theme: s.theme, expertise: s.expertise, renderQuality: s.renderQuality, apiOverride: s.apiOverride });
    if (key === "theme") applyTheme(value);
  },
  setView(patch) {
    set((s) => ({ view: { ...s.view, ...patch } }));
  },
  resetView() {
    set({ view: { ...DEFAULT_VIEW }, tool: "orbit", selectedCamera: null, measurePoints: [], compare: null });
  },
  setTool(tool) {
    set({ tool, measurePoints: tool === "measure" ? get().measurePoints : get().measurePoints });
  },
  selectCamera(i) {
    set({ selectedCamera: i });
  },
  addMeasurePoint(p) {
    const pts = get().measurePoints;
    set({ measurePoints: pts.length >= 2 ? [p] : [...pts, p] });
  },
  clearMeasure() {
    set({ measurePoints: [] });
  },
  setHover(p) {
    set({ hoverPoint: p });
  },
  setCompare(c) {
    set({ compare: c });
  },
  setInspector(tab) {
    set({ inspector: tab, sheetOpen: true });
  },
  setSheetOpen(v) {
    set({ sheetOpen: v });
  },
  setReplaying(v) {
    set({ replaying: v });
  },
}));
