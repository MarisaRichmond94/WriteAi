import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { ChevronLeft, ChevronRight, Moon, Settings as SettingsIcon, Sun } from "lucide-react";
import { fetchBooks, fetchIndexStatus } from "../../api/books";
import { fetchSessions } from "../../api/sessions";
import { fetchSettings } from "../../api/settings";
import { useAppStore } from "../../store/useAppStore";
import { isMockMode, MOCK_BOOKS, MOCK_INDEX_STATUS, MOCK_APP_SETTINGS } from "../../mocks/mockData";
import Sidebar from "../sidebar/Sidebar";
import ChatPane from "../chat/ChatPane";
import TimelinePane from "../timeline/TimelinePane";
import WriterTimelinePane from "../timeline/WriterTimelinePane";
import LocationsPane from "../locations/LocationsPane";
import StatusPane from "../status/StatusPane";
import MetricsPane from "../metrics/MetricsPane";
import CharactersPane from "../characters/CharactersPane";
import PlanPane from "../plan/PlanPane";
import SettingsPane from "../settings/SettingsPane";
import ReviewPane from "../review/ReviewPane";
import NotificationBell from "../notifications/NotificationBell";
import Toast from "../ui/Toast";

function timeOfDay(): string {
  const h = new Date().getHours();
  if (h >= 5 && h < 12) return "Morning";
  if (h >= 12 && h < 18) return "Afternoon";
  return "Evening";
}

function WriterAvatar() {
  const { appSettings, setActivePane } = useAppStore();

  // settings not loaded yet: skeleton circle, no "W" initials flash
  if (appSettings === null) {
    return <span className="h-8 w-8 flex-shrink-0 animate-pulse rounded-full bg-surface-hover ring-1 ring-surface-border" />;
  }

  const name = appSettings.writer_name || "Writer";
  const photoUrl = appSettings.writer_photo_url ?? null;

  const initials = name.trim()
    ? name.trim().split(" ").map((w: string) => w[0]).slice(0, 2).join("").toUpperCase()
    : "W";

  return (
    <button
      onClick={() => setActivePane("settings")}
      title={name}
      className="h-8 w-8 flex-shrink-0 rounded-full overflow-hidden ring-1 ring-surface-border hover:ring-accent transition-all"
    >
      {photoUrl ? (
        <img src={photoUrl} alt={name} className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-accent/20 text-[10px] font-semibold text-accent">
          {initials}
        </div>
      )}
    </button>
  );
}

export default function AppShell() {
  const { setBooks, setBooksLoading, setIndexStatus, showToast, activePane, setActivePane, setAppSettings, appSettings, setChatSessions, setReviewSessions } = useAppStore();
  // light mode applies to the page body only; sidebar stays dark (Loom's pattern)
  const [lightMode, setLightMode] = useState(
    () => localStorage.getItem("writeai-light-mode") === "true"
  );
  const toggleLightMode = () =>
    setLightMode((prev) => {
      const next = !prev;
      localStorage.setItem("writeai-light-mode", String(next));
      return next;
    });

  // Sidebar collapse (Loom's pattern): plain state + localStorage, no store.
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    () => localStorage.getItem("writeai-sidebar-collapsed") === "true"
  );
  const [edgeHovered, setEdgeHovered] = useState(false);
  const edgeLeaveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function toggleSidebar() {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      localStorage.setItem("writeai-sidebar-collapsed", String(next));
      return next;
    });
  }
  function onEdgeEnter() {
    if (edgeLeaveTimer.current) clearTimeout(edgeLeaveTimer.current);
    setEdgeHovered(true);
  }
  function onEdgeLeave() {
    edgeLeaveTimer.current = setTimeout(() => setEdgeHovered(false), 150);
  }

  // ⌥⇧1 toggles the sidebar — matches Loom's shortcut for the same action.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.altKey && e.shiftKey && e.code === "Digit1") {
        e.preventDefault();
        toggleSidebar();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    params.set("pane", activePane);
    window.history.replaceState(null, "", `?${params.toString()}`);
  }, [activePane]);

  useEffect(() => {
    if (isMockMode()) {
      setBooks(MOCK_BOOKS);
      setIndexStatus(MOCK_INDEX_STATUS);
      setAppSettings(MOCK_APP_SETTINGS);
      document.title = MOCK_APP_SETTINGS.site_name;
      return;
    }

    setBooksLoading(true);
    fetchBooks()
      .then(setBooks)
      .catch(() => showToast("Failed to load books from server."))
      .finally(() => setBooksLoading(false));

    fetchIndexStatus()
      .then(setIndexStatus)
      .catch(() => {/* index not ready yet — silent */});

    fetchSettings()
      .then((s) => {
        setAppSettings(s);
        document.title = s.site_name;
      })
      .catch(() => {/* settings not critical — silent */});

    // restore explore/review history from the server
    fetchSessions()
      .then(({ chat, review }) => {
        setChatSessions(chat);
        setReviewSessions(review);
      })
      .catch(() => {/* history not critical — silent */});
  }, []);

  return (
    <div className="flex flex-col h-screen w-screen overflow-hidden">
      {isMockMode() && (
        <div className="flex-shrink-0 flex items-center justify-center bg-amber-400 text-black text-xs font-medium" style={{ height: "25px" }}>
          You are viewing this app in mock mode
        </div>
      )}
      <div className="flex flex-1 overflow-hidden bg-surface">
      {/* Wrapper stays w-3 when collapsed so the hover strip (and handle) stay reachable at the edge */}
      <div
        className={clsx(
          "relative flex-shrink-0 transition-[width] duration-300 ease-in-out",
          sidebarCollapsed ? "w-3" : "w-64"
        )}
        onMouseEnter={onEdgeEnter}
        onMouseLeave={onEdgeLeave}
      >
        <Sidebar collapsed={sidebarCollapsed} />

        <div
          className="absolute inset-y-0 left-full z-40 flex items-center"
          onMouseEnter={onEdgeEnter}
          onMouseLeave={onEdgeLeave}
        >
          <button
            onClick={toggleSidebar}
            title={`${sidebarCollapsed ? "Expand" : "Collapse"} sidebar (⌥⇧1)`}
            aria-label={`${sidebarCollapsed ? "Expand" : "Collapse"} sidebar`}
            className={clsx(
              "flex h-14 items-center justify-center overflow-hidden rounded-r-xl border border-l-0 border-surface-border bg-surface-card text-ink-muted shadow-lg transition-all duration-300 ease-in-out hover:text-ink-primary",
              edgeHovered ? "w-7 opacity-100" : "w-0 opacity-0"
            )}
          >
            {sidebarCollapsed
              ? <ChevronRight className="h-3.5 w-3.5 flex-shrink-0" />
              : <ChevronLeft className="h-3.5 w-3.5 flex-shrink-0" />}
          </button>
        </div>
      </div>
      <main className={clsx("relative flex flex-1 flex-col overflow-hidden", lightMode && "light-body")}>
        <div className="absolute right-6 top-5 z-50 flex items-center gap-2">
          {appSettings === null ? (
            <span className="h-3.5 w-40 animate-pulse rounded bg-surface-hover" />
          ) : (
            <span className="text-xs text-ink-primary">
              Good {timeOfDay()}, {appSettings.writer_name || "Writer"}
            </span>
          )}
          <button
            role="switch"
            aria-checked={lightMode}
            onClick={toggleLightMode}
            title={lightMode ? "Switch to dark mode" : "Switch to light mode"}
            className="mx-1 flex items-center gap-1.5 text-ink-muted hover:text-ink-primary transition-colors"
          >
            <Moon className="h-3 w-3" />
            <span className={clsx(
              "relative inline-flex w-9 h-5 rounded-full transition-colors duration-200",
              lightMode ? "bg-accent" : "bg-surface-hover"
            )}>
              <span className={clsx(
                "absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all duration-200",
                lightMode ? "left-4" : "left-0.5"
              )} />
            </span>
            <Sun className="h-3 w-3" />
          </button>
          <NotificationBell />
          <button
            onClick={() => setActivePane("settings")}
            title="Settings"
            className="rounded-md p-1 text-ink-muted hover:text-ink-primary transition-colors"
          >
            <SettingsIcon className="h-4 w-4" strokeWidth={1.5} />
          </button>
          <WriterAvatar />
        </div>

        {activePane === "explore" && <ChatPane />}
        {activePane === "timeline" && <TimelinePane />}
        {activePane === "writer-timeline" && <WriterTimelinePane />}
        {activePane === "locations" && <LocationsPane />}
        {activePane === "plan" && <PlanPane />}
        {activePane === "review" && <ReviewPane />}
        {activePane === "status" && <StatusPane />}
        {activePane === "spend" && <MetricsPane />}
        {activePane === "characters" && <CharactersPane />}
        {activePane === "settings" && <SettingsPane />}
      </main>
      </div>
      <Toast />
    </div>
  );
}
