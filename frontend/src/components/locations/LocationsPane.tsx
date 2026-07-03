import { useEffect, useMemo, useState } from "react";
import { MapPin, Info, Search, X, ChevronRight, Eye, EyeOff, Pencil, Check } from "lucide-react";
import { clsx } from "clsx";
import { useAppStore } from "../../store/useAppStore";
import {
  fetchLocations,
  renameLocation,
  hideLocation,
  unhideLocation,
  type LocationPlace,
} from "../../api/locations";

function PlaceRow({
  place,
  onChanged,
}: {
  place: LocationPlace;
  onChanged: () => void;
}) {
  const { showToast } = useAppStore();
  const [expanded, setExpanded] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(place.name);

  const commitRename = async () => {
    const next = draft.trim();
    setEditing(false);
    if (!next || next === place.name) {
      setDraft(place.name);
      return;
    }
    try {
      await renameLocation(place.name, next);
      showToast(`Renamed "${place.name}" to "${next}".`);
      onChanged();
    } catch {
      showToast("Failed to rename location.");
      setDraft(place.name);
    }
  };

  const toggleHidden = async () => {
    try {
      if (place.hidden) await unhideLocation(place.name);
      else await hideLocation(place.name);
      onChanged();
    } catch {
      showToast("Failed to update location visibility.");
    }
  };

  return (
    <div className={clsx("group border-b border-surface-border/40 last:border-0", place.hidden && "opacity-40")}>
      <div className="flex items-center gap-2 px-4 py-2.5">
        <button
          onClick={() => setExpanded((v) => !v)}
          className="flex-shrink-0 text-ink-muted hover:text-ink-primary transition-colors"
          title={expanded ? "Hide extracted variants" : "Show extracted variants"}
        >
          <ChevronRight className={clsx("h-3.5 w-3.5 transition-transform", expanded && "rotate-90")} />
        </button>

        {editing ? (
          <input
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commitRename}
            onKeyDown={(e) => {
              if (e.key === "Enter") (e.target as HTMLInputElement).blur();
              else if (e.key === "Escape") { setDraft(place.name); setEditing(false); }
            }}
            className="flex-1 rounded border border-accent/50 bg-surface px-2 py-0.5 text-xs text-ink-primary focus:outline-none"
          />
        ) : (
          <span className="flex-1 truncate text-xs font-medium text-ink-primary">
            {place.name}
          </span>
        )}

        <span className="flex-shrink-0 text-[10px] text-ink-muted">
          {place.chapter_count} chapter{place.chapter_count === 1 ? "" : "s"}
          {place.event_count > 0 && ` · ${place.event_count} event${place.event_count === 1 ? "" : "s"}`}
        </span>

        <button
          onClick={() => (editing ? commitRename() : setEditing(true))}
          title="Rename"
          className="flex-shrink-0 rounded p-1 text-ink-muted opacity-0 transition-all group-hover:opacity-100 hover:bg-surface-hover hover:text-accent"
        >
          {editing ? <Check className="h-3 w-3" /> : <Pencil className="h-3 w-3" />}
        </button>
        <button
          onClick={toggleHidden}
          title={place.hidden ? "Unhide location" : "Hide location"}
          className={clsx(
            "flex-shrink-0 rounded p-1 text-ink-muted transition-all hover:bg-surface-hover hover:text-accent",
            place.hidden ? "opacity-100" : "opacity-0 group-hover:opacity-100"
          )}
        >
          {place.hidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
        </button>
      </div>

      {expanded && (
        <div className="flex flex-wrap gap-1.5 px-10 pb-2.5">
          {place.raw_variants.map((raw) => (
            <span
              key={raw}
              className="rounded-full border border-surface-border px-2 py-0.5 text-[10px] text-ink-muted"
              title="Raw extracted variant mapped to this place"
            >
              {raw}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

export default function LocationsPane() {
  const [places, setPlaces] = useState<LocationPlace[]>([]);
  const [unmapped, setUnmapped] = useState(0);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);
  const [search, setSearch] = useState("");
  const [showHidden, setShowHidden] = useState(false);

  const load = () => {
    fetchLocations(true)
      .then((d) => { setPlaces(d.places); setUnmapped(d.unmapped); setFailed(false); })
      .catch(() => setFailed(true))
      .finally(() => setLoading(false));
  };
  useEffect(load, []);

  const hiddenCount = places.filter((p) => p.hidden).length;

  const groups = useMemo(() => {
    const q = search.trim().toLowerCase();
    const visible = places.filter(
      (p) =>
        (showHidden || !p.hidden) &&
        (!q || p.name.toLowerCase().includes(q) || (p.parent ?? "").toLowerCase().includes(q))
    );
    const settlements = new Set(visible.filter((p) => p.parent).map((p) => p.parent as string));
    const byGroup = new Map<string, LocationPlace[]>();
    for (const p of visible) {
      const key = p.parent ?? (settlements.has(p.name) ? p.name : "Other places");
      if (!byGroup.has(key)) byGroup.set(key, []);
      if (!(p.parent === null && settlements.has(p.name))) byGroup.get(key)!.push(p);
    }
    // settlements that are themselves places get pinned as group headers
    const headerPlaces = new Map(visible.filter((p) => !p.parent && settlements.has(p.name)).map((p) => [p.name, p]));
    return [...byGroup.entries()]
      .sort((a, b) => b[1].reduce((s, p) => s + p.chapter_count, 0) - a[1].reduce((s, p) => s + p.chapter_count, 0))
      .map(([name, members]) => ({
        name,
        header: headerPlaces.get(name) ?? null,
        members: members.sort((a, b) => b.chapter_count - a.chapter_count),
      }));
  }, [places, search, showHidden]);

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 px-6 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <MapPin className="h-6 w-6 flex-shrink-0 text-accent" />
          <div>
            <div className="flex items-center gap-2">
              <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">Locations</p>
              <div className="group relative">
                <Info className="h-3.5 w-3.5 cursor-default text-ink-muted transition-colors hover:text-ink-secondary" />
                <div className="pointer-events-none absolute left-0 top-5 z-50 w-72 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-[11px] leading-relaxed text-ink-muted shadow-lg opacity-0 transition-opacity duration-150 group-hover:opacity-100">
                  Raw extracted location strings are normalized into a two-level gazetteer: settlements and venues.
                  Non-places are dropped — a missing location beats a bad one. Rename or hide places here;
                  your decisions persist across re-indexing.
                </div>
              </div>
            </div>
            <p className="mt-0.5 text-[11px] text-ink-muted">
              The places of your series, grouped by settlement. Expand a place to see its raw variants.
            </p>
          </div>
        </div>
        <div className="mt-3 border-t border-surface-border" />
      </div>

      {/* Controls */}
      <div className="flex-shrink-0 flex items-center gap-2 px-6 pb-3">
        <div className="relative flex-1 max-w-sm">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search locations..."
            className="w-full rounded-md border border-surface-border bg-surface py-1.5 pl-8 pr-8 text-xs text-ink-primary placeholder:text-ink-muted focus:border-accent focus:outline-none"
          />
          {search && (
            <button onClick={() => setSearch("")} className="absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink-primary">
              <X className="h-3 w-3" />
            </button>
          )}
        </div>
        <span className="flex-1" />
        {unmapped > 0 && (
          <span className="text-[10px] text-ink-muted" title="Raw strings judged not to be usable places">
            {unmapped} raw strings dropped as non-places
          </span>
        )}
        <button
          onClick={() => setShowHidden((v) => !v)}
          className={clsx(
            "flex flex-shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition-colors",
            showHidden ? "bg-accent/20 text-accent ring-1 ring-accent/40" : "bg-surface-card text-ink-secondary hover:text-ink-primary"
          )}
        >
          {showHidden ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
          Hidden ({hiddenCount})
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 overflow-y-auto px-6 pb-6">
        {loading ? (
          <div className="space-y-3 pt-2">
            {[...Array(6)].map((_, i) => (
              <div key={i} className="h-9 animate-pulse rounded-lg bg-surface-card" style={{ width: `${85 - (i % 3) * 10}%` }} />
            ))}
          </div>
        ) : failed || places.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <MapPin className="h-8 w-8 text-ink-muted/40" strokeWidth={1.5} />
            <div>
              <p className="text-sm font-medium text-ink-secondary">
                {failed ? "Failed to load locations." : "No locations mapped yet"}
              </p>
              <p className="mt-0.5 text-[11px] text-ink-muted">
                {failed ? "Try refreshing." : "Run enrichment to build the location gazetteer."}
              </p>
            </div>
          </div>
        ) : (
          <div className="space-y-4 pt-1">
            {groups.map((g) => (
              <div key={g.name} className="overflow-hidden rounded-lg border border-surface-border bg-surface-card">
                <div className="flex items-center gap-2 border-b border-surface-border bg-surface px-4 py-2">
                  <p className="text-[10px] font-bold uppercase tracking-widest text-ink-primary">{g.name}</p>
                  {g.header && (
                    <span className="text-[10px] text-ink-muted">
                      {g.header.chapter_count} chapter{g.header.chapter_count === 1 ? "" : "s"}
                    </span>
                  )}
                </div>
                {g.header && <PlaceRow place={g.header} onChanged={load} />}
                {g.members.map((p) => (
                  <PlaceRow key={p.name} place={p} onChanged={load} />
                ))}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
