import { lazy, Suspense, useEffect, useState } from "react";
import { BrowserRouter, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { Icon, ToastProvider, Wordmark } from "../components/ui.jsx";
import { applyTheme, useStore } from "../state/store.js";
import { detectBackend } from "../api/client.js";
import StudioPage from "../pages/StudioPage.jsx";

const ProjectsPage = lazy(() => import("../pages/ProjectsPage.jsx"));
const ExplorePage = lazy(() => import("../pages/ExplorePage.jsx"));
const LearnPage = lazy(() => import("../pages/LearnPage.jsx"));
const SettingsPage = lazy(() => import("../pages/SettingsPage.jsx"));
const ScenePage = lazy(() => import("../pages/ScenePage.jsx"));
const ComparePage = lazy(() => import("../pages/ComparePage.jsx"));

const NAV = [
  { to: "/", label: "studio", icon: "sparkle", end: true },
  { to: "/projects", label: "projects", icon: "grid" },
  { to: "/explore", label: "explore", icon: "compass" },
  { to: "/learn", label: "learn", icon: "book" },
  { to: "/settings", label: "settings", icon: "gear" },
];

function ThemeButton() {
  const theme = useStore((s) => s.theme);
  const setPref = useStore((s) => s.setPref);
  const dark = document.documentElement.dataset.theme === "dark";
  return (
    <button
      className="btn btn-ghost btn-icon"
      onClick={() => setPref("theme", dark ? "light" : "dark")}
      aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}
      title={`Theme: ${theme}`}
    >
      <Icon name={dark ? "sun" : "moon"} />
    </button>
  );
}

function Shell({ children }) {
  const loc = useLocation();
  const immersive = loc.pathname.startsWith("/scene") || loc.pathname.startsWith("/compare");
  const [backend, setBackend] = useState(null);
  useEffect(() => {
    detectBackend().then(setBackend);
  }, []);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [loc.pathname]);

  return (
    <div className="flex min-h-full flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-ink focus:px-3 focus:py-2 focus:text-bg">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-line bg-bg">
        <div className={`mx-auto flex h-12 items-center gap-8 px-4 sm:px-6 ${immersive ? "" : "max-w-[1180px]"}`}>
          <NavLink to="/" className="text-ink" aria-label="sceneform home">
            <Wordmark />
          </NavLink>
          <nav aria-label="Primary" className="hidden h-full items-stretch gap-5 md:flex">
            {NAV.map((n) => (
              <NavLink
                key={n.to}
                to={n.to}
                end={n.end}
                className={({ isActive }) =>
                  `flex items-center border-b-2 text-[13px] transition-colors ${isActive ? "border-ink text-ink" : "border-transparent text-muted hover:text-ink"}`
                }
              >
                {n.label}
              </NavLink>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3">
            {backend && (
              <span
                className="hidden font-mono text-[11px] text-muted sm:inline"
                title={backend.available ? "A sceneform reconstruction server is connected" : "No reconstruction server is connected; this site shows precomputed scenes"}
              >
                {backend.available ? `server: connected · v${backend.version}` : "server: none · viewer only"}
              </span>
            )}
            <ThemeButton />
          </div>
        </div>
      </header>
      <main id="main" className="flex-1 pb-16 md:pb-0">
        {children}
      </main>
      {!immersive && (
        <footer className="border-t border-line">
          <div className="mx-auto flex max-w-[1180px] flex-wrap items-center justify-between gap-2 px-4 py-5 font-mono text-[11px] text-faint sm:px-6">
            <span>sceneform — multi-view 3D reconstruction</span>
            <span>COLMAP · Depth Anything V2 · msplat · Spark</span>
          </div>
        </footer>
      )}
      <nav aria-label="Primary" className="fixed inset-x-0 bottom-0 z-30 flex border-t border-line bg-bg md:hidden" style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) => `flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] ${isActive ? "text-ink" : "text-faint"}`}
          >
            <Icon name={n.icon} size={19} />
            {n.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

function Loading() {
  return (
    <div className="flex h-[60vh] items-center justify-center text-muted" role="status">
      Loading…
    </div>
  );
}

export default function App() {
  const theme = useStore((s) => s.theme);
  useEffect(() => {
    applyTheme(theme);
    if (theme !== "system") return;
    const mq = matchMedia("(prefers-color-scheme: dark)");
    const on = () => applyTheme("system");
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, [theme]);

  return (
    <BrowserRouter>
      <ToastProvider>
        <Shell>
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route path="/" element={<StudioPage />} />
              <Route path="/projects" element={<ProjectsPage />} />
              <Route path="/explore" element={<ExplorePage />} />
              <Route path="/learn" element={<LearnPage />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/scene/example/:exampleId" element={<ScenePage />} />
              <Route path="/scene/project/:projectId/:runId" element={<ScenePage />} />
              <Route path="/compare" element={<ComparePage />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </Suspense>
        </Shell>
      </ToastProvider>
    </BrowserRouter>
  );
}

function NotFound() {
  return (
    <div className="mx-auto max-w-xl px-6 py-24 text-center">
      <h1 className="serif text-3xl">Page not found</h1>
      <p className="mt-3 text-muted">That page doesn’t exist. Try the studio or an example scene.</p>
      <NavLink to="/" className="btn btn-primary mt-6">
        Go to studio
      </NavLink>
    </div>
  );
}
