import { useEffect } from "react";
import { Settings as SettingsIcon } from "lucide-react";
import { fetchBooks, fetchIndexStatus } from "../../api/books";
import { fetchSessions } from "../../api/sessions";
import { fetchSettings } from "../../api/settings";
import { useAppStore } from "../../store/useAppStore";
import { isMockMode, MOCK_BOOKS, MOCK_INDEX_STATUS, MOCK_APP_SETTINGS } from "../../mocks/mockData";
import Sidebar from "../sidebar/Sidebar";
import ChatPane from "../chat/ChatPane";
import TimelinePane from "../timeline/TimelinePane";
import StatusPane from "../status/StatusPane";
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
  const name = appSettings?.writer_name ?? "Writer";
  const photoUrl = appSettings?.writer_photo_url ?? null;

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
      <Sidebar />
      <main className="relative flex flex-1 flex-col overflow-hidden">
        <div className="absolute right-6 top-5 z-50 flex items-center gap-2">
          <span className="text-xs text-white">
            Good {timeOfDay()}, {appSettings?.writer_name ?? "Writer"}
          </span>
          <NotificationBell />
          <button
            onClick={() => setActivePane("settings")}
            title="Settings"
            className="rounded-md p-1 text-white/60 hover:text-white transition-colors"
          >
            <SettingsIcon className="h-4 w-4" strokeWidth={1.5} />
          </button>
          <WriterAvatar />
        </div>

        {activePane === "explore" && <ChatPane />}
        {activePane === "timeline" && <TimelinePane />}
        {activePane === "plan" && <PlanPane />}
        {activePane === "review" && <ReviewPane />}
        {activePane === "status" && <StatusPane />}
        {activePane === "characters" && <CharactersPane />}
        {activePane === "settings" && <SettingsPane />}
      </main>
      </div>
      <Toast />
    </div>
  );
}
