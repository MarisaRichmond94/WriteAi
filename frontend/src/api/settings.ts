// Adapter: expose this app's settings in the reference AppSettings shape.
import type { AppSettings } from "../types";

interface BackendSettings {
  fields: { key: string; value: string }[];
  profile: { writer_name: string; site_name: string; writer_photo_url?: string | null;
             book_order?: string[]; sync_time?: string; auto_sync_enabled?: boolean;
             auto_enrich_enabled?: boolean;
             backup_retention_days?: number; viewer_light_mode?: boolean };
  discovered_books?: string[];
}

async function backendSettings(): Promise<BackendSettings> {
  const res = await fetch("/api/settings");
  if (!res.ok) throw new Error(`Failed to fetch settings: ${res.statusText}`);
  return res.json();
}

export async function fetchSettings(): Promise<AppSettings> {
  const data = await backendSettings();
  const f = (k: string) => data.fields.find((x) => x.key === k)?.value ?? "";
  return {
    site_name: data.profile.site_name || "The Archive",
    source_books_dir: f("BOOKS_DIR"),
    books_dir: f("TEXT_EXPORT_DIR"),
    data_dir: f("DATA_DIR"),
    backup_retention_days: data.profile.backup_retention_days ?? 30,
    sync_time: data.profile.sync_time ?? "02:30",
    auto_sync_enabled: data.profile.auto_sync_enabled ?? true,
    auto_enrich_enabled: data.profile.auto_enrich_enabled ?? true,
    book_order: data.profile.book_order ?? [],
    query_model: f("QUERY_MODEL"),
    extraction_model: f("EXTRACTION_MODEL"),
    odv_model: "",
    discovered_books: data.discovered_books ?? [],
    anthropic_api_key_preview: f("ANTHROPIC_API_KEY"),
    openai_api_key_preview: f("OPENAI_API_KEY"),
    writer_name: data.profile.writer_name || "Writer",
    writer_photo_url: data.profile.writer_photo_url ?? null,
    viewer_light_mode: data.profile.viewer_light_mode ?? true,
  };
}

export async function saveSettings(
  updates: Partial<AppSettings> & { anthropic_api_key?: string; openai_api_key?: string },
): Promise<void> {
  const values: Record<string, string> = {};
  if (updates.source_books_dir !== undefined) values.BOOKS_DIR = updates.source_books_dir;
  if (updates.books_dir !== undefined) values.TEXT_EXPORT_DIR = updates.books_dir;
  if (updates.data_dir !== undefined) values.DATA_DIR = updates.data_dir;
  if (updates.query_model !== undefined) values.QUERY_MODEL = updates.query_model;
  if (updates.extraction_model !== undefined) values.EXTRACTION_MODEL = updates.extraction_model;
  if (updates.anthropic_api_key) values.ANTHROPIC_API_KEY = updates.anthropic_api_key;
  if (updates.openai_api_key) values.OPENAI_API_KEY = updates.openai_api_key;

  const profile: Record<string, unknown> = {};
  if (updates.writer_name !== undefined) profile.writer_name = updates.writer_name;
  if (updates.site_name !== undefined) profile.site_name = updates.site_name;
  if (updates.book_order !== undefined) profile.book_order = updates.book_order;
  if (updates.writer_photo_url !== undefined) profile.writer_photo_url = updates.writer_photo_url;
  if (updates.sync_time !== undefined) profile.sync_time = updates.sync_time;
  if (updates.auto_sync_enabled !== undefined) profile.auto_sync_enabled = updates.auto_sync_enabled;
  if (updates.auto_enrich_enabled !== undefined) profile.auto_enrich_enabled = updates.auto_enrich_enabled;
  if (updates.backup_retention_days !== undefined) profile.backup_retention_days = updates.backup_retention_days;
  if (updates.viewer_light_mode !== undefined) profile.viewer_light_mode = updates.viewer_light_mode;

  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ values, profile: Object.keys(profile).length ? profile : null }),
  });
  if (!res.ok) throw new Error(`Failed to save settings: ${res.statusText}`);
}

export async function fetchDiscoveredBooks(): Promise<string[]> {
  const res = await fetch("/api/settings/validate", { method: "POST" });
  if (!res.ok) return [];
  const data = (await res.json()) as { books: string[] };
  return data.books ?? [];
}

export async function uploadWriterPhoto(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch("/api/settings/writer-photo", { method: "POST", body: form });
  if (!res.ok) throw new Error(`Failed to upload photo: ${res.statusText}`);
  const data = (await res.json()) as { photo_url: string };
  return data.photo_url;
}

export async function deleteWriterPhoto(): Promise<void> {
  await fetch("/api/settings/writer-photo", { method: "DELETE" });
}

export function bookSlug(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
}

// A manual upload overrides the auto-detected Dust Jacket cover for that book.
export async function uploadBookCover(slug: string, file: File): Promise<void> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`/api/settings/book-cover/${encodeURIComponent(slug)}`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) throw new Error(`Failed to upload cover: ${res.statusText}`);
}

// Removing the manual override reverts to the auto-detected cover.
export async function deleteBookCover(slug: string): Promise<void> {
  const res = await fetch(`/api/settings/book-cover/${encodeURIComponent(slug)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(`Failed to remove cover: ${res.statusText}`);
}

export async function pickFolder(current?: string): Promise<string | null> {
  // native macOS folder chooser, presented by the local server
  const res = await fetch("/api/settings/pick-folder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ current: current ?? null }),
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data.path ?? null;
}
