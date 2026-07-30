import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import { ChevronLeft, ChevronRight } from "lucide-react";
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
import AppHeader from "./AppHeader";
import Toast from "../ui/Toast";


export default function AppShell() {
  const { setBooks, setBooksLoading, setIndexStatus, showToast, activePane, setActivePane, setAppSettings, setChatSessions, setReviewSessions } = useAppStore();
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
      {/* Full-width header above the sidebar row, matching Loom (KAN-7). The
          cluster this replaces lived inside <main>, so it began to the right of
          the sidebar; spanning the full width is what makes the two apps read as
          one product. Sits below the mock-mode banner, which stays topmost. */}
      <AppHeader lightMode={lightMode} onToggleLightMode={toggleLightMode} />

      <div className="flex flex-1 overflow-hidden bg-surface">
      {/* Wrapper stays w-3 when collapsed so the hover strip (and handle) stay reachable at the edge */}
      <div
        className={clsx(
          "relative flex-shrink-0 transition-[width] duration-300 ease-in-out",
          sidebarCollapsed ? "w-3" : "w-56"
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
      {/* pt-4 restores the breathing room the per-pane title blocks used to
          provide (KAN-7) — without it pane content sits flush against the
          header's bottom border. Applied here once rather than in each of the
          nine panes, so it cannot drift between them.

          Spend is excluded: its charts are laid out to sit flush, and the
          writer wants that one left alone. */}
      <main
        className={clsx(
          "relative flex flex-1 flex-col overflow-hidden",
          activePane !== "spend" && "pt-4",
          lightMode && "light-body"
        )}
      >
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
