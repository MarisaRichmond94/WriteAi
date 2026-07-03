import type { Notification, NotificationType } from "../types";

// Server-backed notifications (writer_data/notifications.json): the backend
// emits sync_complete / extraction_complete events; the bell polls here.

export async function createNotification(_payload: {
  type: NotificationType;
  title: string;
  body: string;
  book?: string | null;
}): Promise<void> {
  // notifications are emitted server-side; the UI never creates them
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
