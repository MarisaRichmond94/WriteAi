import type { ChatSession, ReviewSession } from "../types";

type Kind = "chat" | "review";

// Revive Date fields lost in JSON round-trips (components call Date methods).
function reviveDates<T extends { timestamp: Date; messages: { timestamp: Date }[] }>(s: T): T {
  return {
    ...s,
    timestamp: new Date(s.timestamp),
    messages: (s.messages ?? []).map((m) => ({ ...m, timestamp: new Date(m.timestamp) })),
  };
}

export async function fetchSessions(): Promise<{ chat: ChatSession[]; review: ReviewSession[] }> {
  const res = await fetch("/api/sessions");
  if (!res.ok) throw new Error(`Failed to fetch sessions: ${res.statusText}`);
  const data = await res.json();
  return {
    chat: (data.chat ?? []).map(reviveDates),
    review: (data.review ?? []).map(reviveDates),
  };
}

// Write-through helpers: fire-and-forget from store actions — a failed save
// must never break the live UI, so callers swallow rejections.
export async function persistSession(kind: Kind, session: ChatSession | ReviewSession): Promise<void> {
  await fetch(`/api/sessions/${kind}/${encodeURIComponent(session.id)}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(session),
  });
}

export async function removeSession(kind: Kind, id: string): Promise<void> {
  await fetch(`/api/sessions/${kind}/${encodeURIComponent(id)}`, { method: "DELETE" });
}
