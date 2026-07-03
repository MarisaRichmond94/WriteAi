// Writer-authored timeline events — the writer's own events, distinct from
// the AI-extracted events served by /api/events.

export interface WriterEventTag {
  book: string;
  chapter: number;
}

export interface WriterEvent {
  id: string;
  title: string;
  date: string | null;
  description: string;
  characters: string[];
  location: string | null;
  book_chapters: WriterEventTag[];
  created_at: string;
  updated_at: string;
}

export interface WriterEventInput {
  title: string;
  date: string | null;
  description: string;
  characters: string[];
  location: string | null;
  book_chapters: WriterEventTag[];
}

const BASE = "/api/writer-events";

export async function fetchWriterEvents(): Promise<{
  events: WriterEvent[];
  locations: string[];
}> {
  const res = await fetch(BASE);
  if (!res.ok) throw new Error("Failed to fetch writer events");
  return res.json();
}

export async function createWriterEvent(input: WriterEventInput): Promise<WriterEvent> {
  const res = await fetch(BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error("Failed to create event");
  return res.json();
}

export async function updateWriterEvent(
  id: string,
  input: WriterEventInput,
): Promise<WriterEvent> {
  const res = await fetch(`${BASE}/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error("Failed to update event");
  return res.json();
}

export async function deleteWriterEvent(id: string): Promise<void> {
  const res = await fetch(`${BASE}/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete event");
}

export async function addWriterLocation(name: string): Promise<{ locations: string[] }> {
  const res = await fetch(`${BASE}/locations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error("Failed to add location");
  return res.json();
}
