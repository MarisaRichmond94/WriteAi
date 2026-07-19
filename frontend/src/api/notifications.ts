import type { Notification, NotificationType } from "../types";

// Server-backed notifications (writer_data/notifications.json): the backend
// emits sync_complete / extraction_complete events; the bell polls here.
// UI-originated events post into the same inbox via createNotification —
// pair it with useAppStore's refreshBell() so the bell updates immediately
// instead of on the next poll.

export async function createNotification(payload: {
  type: NotificationType;
  title: string;
  body: string;
  book?: string | null;
  action_url?: string | null;
}): Promise<void> {
  try {
    await fetch("/api/notifications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    // best-effort — the bell's 30s poll is the backstop
  }
}

// Fire-and-forget breadcrumb into the server's audit trail
// (logs/audit.jsonl) — for traceable-but-not-bell-worthy events like poll
// timeouts and queued retries.
export function logAudit(kind: string, message: string, fields: Record<string, unknown> = {}): void {
  fetch("/api/audit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, message, fields }),
  }).catch(() => {});
}

export async function fetchNotifications(): Promise<Notification[]> {
  const res = await fetch("/api/notifications");
  if (!res.ok) return [];
  return res.json();
}

export async function markOneRead(id: string): Promise<void> {
  await fetch(`/api/notifications/${encodeURIComponent(id)}/read`, { method: "POST" });
}

export async function markAllRead(): Promise<void> {
  await fetch("/api/notifications/read-all", { method: "POST" });
}

export async function deleteNotification(id: string): Promise<void> {
  await fetch(`/api/notifications/${encodeURIComponent(id)}`, { method: "DELETE" });
}

export async function clearAllNotifications(): Promise<void> {
  await fetch("/api/notifications", { method: "DELETE" });
}
