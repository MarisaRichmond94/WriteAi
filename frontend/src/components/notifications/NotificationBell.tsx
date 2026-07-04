import { useEffect, useRef, useState } from "react";
import { Bell, X, CheckCheck } from "lucide-react";
import { clsx } from "clsx";
import type { Notification } from "../../types";
import {
  fetchNotifications,
  markOneRead,
  markAllRead,
  deleteNotification,
} from "../../api/notifications";
import { useAppStore } from "../../store/useAppStore";

const POLL_INTERVAL_MS = 30_000;

function formatRelative(isoString: string): string {
  const then = new Date(isoString);
  const diffMs = Date.now() - then.getTime();
  const diffMin = Math.floor(diffMs / 60_000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.floor(diffHr / 24)}d ago`;
}

const TYPE_LABEL: Record<string, string> = {
  extraction_ready: "Needs Review",
  extraction_complete: "Complete",
  sync_complete: "Sync",
  error: "Error",
};

const TYPE_COLOR: Record<string, string> = {
  extraction_ready: "text-amber-400",
  extraction_complete: "text-emerald-400",
  sync_complete: "text-sky-400",
  error: "text-red-400",
};

export default function NotificationBell() {
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const [open, setOpen] = useState(false);
  const [prevUnread, setPrevUnread] = useState(0);
  const [pulse, setPulse] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const { setActivePane, bellRefreshSignal } = useAppStore();

  const unreadCount = notifications.filter((n) => !n.read).length;

  async function load() {
    try {
      const data = await fetchNotifications();
      setNotifications(data);
    } catch {
      // silent
    }
  }

  useEffect(() => {
    load();
    const id = setInterval(load, POLL_INTERVAL_MS);
    return () => clearInterval(id);
  }, []);

  // Immediate reload when the UI just created a notification
  useEffect(() => {
    if (bellRefreshSignal) load();
  }, [bellRefreshSignal]);

  // Pulse when new unread arrive
  useEffect(() => {
    if (unreadCount > prevUnread) {
      setPulse(true);
      const t = setTimeout(() => setPulse(false), 2000);
      setPrevUnread(unreadCount);
      return () => clearTimeout(t);
    }
    setPrevUnread(unreadCount);
  }, [unreadCount]);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  async function handleMarkRead(id: string) {
    await markOneRead(id);
    setNotifications((prev) =>
      prev.map((n) => (n.id === id ? { ...n, read: true } : n))
    );
  }

  async function handleDelete(id: string) {
    await deleteNotification(id);
    setNotifications((prev) => prev.filter((n) => n.id !== id));
  }

  async function handleMarkAll() {
    await markAllRead();
    setNotifications((prev) => prev.map((n) => ({ ...n, read: true })));
  }

  function handleRunExtraction(bookSlug: string | null) {
    setOpen(false);
    setActivePane("import");
    // Navigation to the specific book is handled by the ImportPane
  }

  function handleActionUrl(n: Notification) {
    if (!n.action_url) return;
    setOpen(false);
    if (!n.read) handleMarkRead(n.id);
    const params = new URLSearchParams(new URL(n.action_url, window.location.href).search);
    const pane = params.get("pane");
    if (pane) {
      setActivePane(pane as Parameters<typeof setActivePane>[0]);
      window.history.pushState(null, "", n.action_url);
    }
  }

  return (
    <div className="relative" ref={dropdownRef}>
      <button
        onClick={() => setOpen((o) => !o)}
        className={clsx(
          "relative flex h-8 w-8 items-center justify-center rounded-full transition-colors",
          "text-ink-secondary hover:text-ink-primary hover:bg-surface",
          pulse && "animate-pulse"
        )}
        title="Notifications"
      >
        <Bell className="h-4 w-4" strokeWidth={1.5} />
        {unreadCount > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white">
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-10 z-50 w-80 rounded-lg border border-surface-border bg-surface-card shadow-xl">
          {/* Header */}
          <div className="flex items-center justify-between border-b border-surface-border px-3 py-2">
            <span className="text-xs font-semibold text-ink-primary">Notifications</span>
            {unreadCount > 0 && (
              <button
                onClick={handleMarkAll}
                className="flex items-center gap-1 text-[11px] text-ink-muted hover:text-ink-secondary transition-colors"
                title="Mark all read"
              >
                <CheckCheck className="h-3 w-3" />
                Mark all read
              </button>
            )}
          </div>

          {/* List */}
          <div className="max-h-80 overflow-y-auto">
            {notifications.length === 0 ? (
              <div className="px-4 py-6 text-center text-xs text-ink-muted">
                No notifications
              </div>
            ) : (
              notifications.map((n) => (
                <div
                  key={n.id}
                  className={clsx(
                    "group relative border-b border-surface-border/50 px-3 py-2.5 last:border-0",
                    !n.read && "bg-accent/5"
                  )}
                  onClick={() => !n.read && handleMarkRead(n.id)}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span
                          className={clsx(
                            "text-[10px] font-semibold",
                            TYPE_COLOR[n.type] ?? "text-ink-muted"
                          )}
                        >
                          {TYPE_LABEL[n.type] ?? n.type}
                        </span>
                        {!n.read && (
                          <span className="h-1.5 w-1.5 rounded-full bg-accent" />
                        )}
                      </div>
                      <p className="mt-0.5 text-xs font-medium text-ink-primary leading-snug">
                        {n.title}
                      </p>
                      <p className="mt-0.5 text-[11px] text-ink-muted leading-snug line-clamp-2">
                        {n.body}
                      </p>
                      <div className="mt-1.5 flex items-center gap-2">
                        <span className="text-[10px] text-ink-muted">
                          {formatRelative(n.created_at)}
                        </span>
                        {n.type === "extraction_ready" && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleRunExtraction(n.book);
                            }}
                            className="text-[10px] font-semibold text-accent hover:underline"
                          >
                            Open Import
                          </button>
                        )}
                        {n.action_url && n.type !== "extraction_ready" && (
                          <button
                            onClick={(e) => {
                              e.stopPropagation();
                              handleActionUrl(n);
                            }}
                            className="text-[10px] font-semibold text-accent hover:underline"
                          >
                            View
                          </button>
                        )}
                      </div>
                    </div>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleDelete(n.id);
                      }}
                      className="flex-shrink-0 rounded p-0.5 text-ink-muted opacity-0 transition-opacity group-hover:opacity-100 hover:text-ink-primary"
                      title="Dismiss"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
