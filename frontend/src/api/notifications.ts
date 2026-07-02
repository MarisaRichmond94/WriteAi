// Adapter shim: no notification backend yet — the bell renders an empty
// inbox. (Reserved for future ingest/enrich completion events.)
import type { Notification, NotificationType } from "../types";

export async function createNotification(_payload: {
  type: NotificationType;
  title: string;
  body: string;
  book?: string | null;
}): Promise<void> {}

export async function fetchNotifications(): Promise<Notification[]> {
  return [];
}

export async function markOneRead(_id: string): Promise<void> {}

export async function markAllRead(): Promise<void> {}

export async function deleteNotification(_id: string): Promise<void> {}
