export interface LocationPlace {
  name: string;
  parent: string | null;
  raw_variants: string[];
  chapter_count: number;
  event_count: number;
  hidden: boolean;
}

export async function fetchLocations(includeHidden = false): Promise<{
  places: LocationPlace[];
  unmapped: number;
}> {
  const res = await fetch(`/api/locations?include_hidden=${includeHidden}`);
  if (!res.ok) throw new Error(`Failed to fetch locations: ${res.statusText}`);
  return res.json();
}

export async function renameLocation(fromName: string, toName: string): Promise<void> {
  const res = await fetch("/api/locations/rename", {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ from_name: fromName, to_name: toName }),
  });
  if (!res.ok) throw new Error("Failed to rename location");
}

export async function hideLocation(name: string): Promise<void> {
  const res = await fetch("/api/locations/hide", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error("Failed to hide location");
}

export async function unhideLocation(name: string): Promise<void> {
  const res = await fetch(`/api/locations/hide/${encodeURIComponent(name)}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to unhide location");
}
