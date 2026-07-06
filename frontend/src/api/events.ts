import type { TimelineEvent } from "../types";
import { MOCK_EVENTS } from "../mocks/timelineMocks";
import { isMockMode } from "../mocks/mockData";

const BASE = "/api/events";

export async function fetchEvents(filters?: {
  book?: string;
  pov?: string;
  granularity?: string;
  order?: "narrative" | "story";
}): Promise<TimelineEvent[]> {
  if (isMockMode()) {
    let results = MOCK_EVENTS;
    if (filters?.book) results = results.filter(e => e.book === filters.book);
    if (filters?.pov) results = results.filter(e => e.participants.includes(filters.pov!));
    if (filters?.granularity) results = results.filter(e => e.granularity === filters.granularity);
    return results;
  }

  const params = new URLSearchParams();
  if (filters?.book) params.set("book", filters.book);
  if (filters?.pov) params.set("pov", filters.pov);
  if (filters?.granularity) params.set("granularity", filters.granularity);
  if (filters?.order && filters.order !== "narrative") params.set("order", filters.order);

  const url = params.size > 0 ? `${BASE}?${params}` : BASE;
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch events");
  return res.json();
}

/** Whether story-chronological ordering is available (ENABLE_STORY_ORDER on
 * AND the chapter_timeline table populated). Drives the order toggle. */
export async function fetchStoryOrderAvailable(): Promise<boolean> {
  if (isMockMode()) return false;
  try {
    const res = await fetch(`${BASE}/meta`);
    if (!res.ok) return false;
    return Boolean((await res.json()).story_order_available);
  } catch {
    return false;
  }
}
