import { useState, useEffect, useRef, useCallback } from "react";
import { createPortal } from "react-dom";
import { Users, Camera, ChevronRight, RefreshCw, Info, Search, Link, Sparkles, X, Pencil, Eye, EyeOff } from "lucide-react";
import { clsx } from "clsx";
import { useAppStore } from "../../store/useAppStore";
import type { CharacterSummary, CharacterDetail, CharacterBookDetail, CharacterRelationship, KnowledgeItem, ArcEntry, AliasWithProvenance, Citation } from "../../types";
import ChapterViewer from "../chat/ChapterViewer";
import { chapterLabel } from "../../lib/format";
import {
  fetchCharacters,
  fetchCharacterDetail,
  fetchCharacterBookDetail,
  uploadCharacterPhoto,
  triggerExtract,
  hideCharacter,
  unhideCharacter,
} from "../../api/characters";
import ConfirmModal from "../ui/ConfirmModal";
import CharacterEditModal from "./CharacterEditModal";

// ── POV color palette (mirrors CitationCard) ─────────────────────────────────
const POV_PALETTE = [
  { bg: "bg-rose-500/20", text: "text-rose-300", ring: "ring-rose-500/40" },
  { bg: "bg-sky-500/20", text: "text-sky-300", ring: "ring-sky-500/40" },
  { bg: "bg-violet-500/20", text: "text-violet-300", ring: "ring-violet-500/40" },
  { bg: "bg-amber-500/20", text: "text-amber-300", ring: "ring-amber-500/40" },
  { bg: "bg-teal-500/20", text: "text-teal-300", ring: "ring-teal-500/40" },
  { bg: "bg-fuchsia-500/20", text: "text-fuchsia-300", ring: "ring-fuchsia-500/40" },
];
function nameColor(name: string) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) & 0xffff;
  return POV_PALETTE[hash % POV_PALETTE.length];
}

function bookId(name: string) {
  return name.toLowerCase().replace(/'/g, "").replace(/ /g, "-");
}

// ── Relationship sort ─────────────────────────────────────────────────────────
type RelSort = "appearances" | "type" | "name";
const REL_SORT_CYCLE: RelSort[] = ["appearances", "type", "name"];
const REL_SORT_LABEL: Record<RelSort, string> = { appearances: "by appearances", type: "by type", name: "by name" };
function sortRels(rels: CharacterRelationship[], sort: RelSort): CharacterRelationship[] {
  const cmp = (a: CharacterRelationship, b: CharacterRelationship): number => {
    if (sort === "appearances") return (b.appearance_count ?? 0) - (a.appearance_count ?? 0);
    if (sort === "type") return (a.gendered_status || a.status || "").localeCompare(b.gendered_status || b.status || "");
    return a.target.localeCompare(b.target);
  };
  return [...rels].sort(cmp);
}

// ── Photo crop modal ──────────────────────────────────────────────────────────
const CROP_PREVIEW_SIZE = 240;
const CROP_OUTPUT_SIZE = 400;

function PhotoCropModal({
  file,
  onConfirm,
  onCancel,
}: {
  file: File;
  onConfirm: (blob: Blob) => void;
  onCancel: () => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const imgRef = useRef<HTMLImageElement | null>(null);
  const [imgLoaded, setImgLoaded] = useState(false);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [scale, setScale] = useState(1);
  const dragging = useRef(false);
  const dragStart = useRef<{ mx: number; my: number; ox: number; oy: number } | null>(null);

  // Load image from file
  useEffect(() => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      imgRef.current = img;
      setImgLoaded(true);
    };
    img.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file]);

  // Keyboard: Escape to cancel
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onCancel]);

  // Render canvas
  useEffect(() => {
    const canvas = canvasRef.current;
    const img = imgRef.current;
    if (!canvas || !img || !imgLoaded) return;
    const ctx = canvas.getContext("2d")!;
    const size = CROP_PREVIEW_SIZE;
    const baseScale = size / Math.min(img.width, img.height);
    const drawW = img.width * baseScale * scale;
    const drawH = img.height * baseScale * scale;
    const cx = size / 2;
    const cy = size / 2;
    ctx.clearRect(0, 0, size, size);
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, size / 2, 0, Math.PI * 2);
    ctx.clip();
    ctx.drawImage(img, cx + offset.x - drawW / 2, cy + offset.y - drawH / 2, drawW, drawH);
    ctx.restore();
  }, [imgLoaded, offset, scale]);

  const handleMouseDown = (e: React.MouseEvent) => {
    dragging.current = true;
    dragStart.current = { mx: e.clientX, my: e.clientY, ox: offset.x, oy: offset.y };
  };
  const handleMouseMove = (e: React.MouseEvent) => {
    if (!dragging.current || !dragStart.current) return;
    setOffset({
      x: dragStart.current.ox + (e.clientX - dragStart.current.mx),
      y: dragStart.current.oy + (e.clientY - dragStart.current.my),
    });
  };
  const handleMouseUp = () => { dragging.current = false; };

  const handleWheel = (e: React.WheelEvent) => {
    e.preventDefault();
    setScale(s => Math.max(0.5, Math.min(4, s - e.deltaY * 0.001)));
  };

  const handleConfirm = () => {
    const img = imgRef.current;
    if (!img) return;
    const offscreen = document.createElement("canvas");
    offscreen.width = CROP_OUTPUT_SIZE;
    offscreen.height = CROP_OUTPUT_SIZE;
    const ctx = offscreen.getContext("2d")!;
    const ratio = CROP_OUTPUT_SIZE / CROP_PREVIEW_SIZE;
    const baseScale = CROP_PREVIEW_SIZE / Math.min(img.width, img.height);
    const drawW = img.width * baseScale * scale * ratio;
    const drawH = img.height * baseScale * scale * ratio;
    const cx = CROP_OUTPUT_SIZE / 2;
    const cy = CROP_OUTPUT_SIZE / 2;
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, CROP_OUTPUT_SIZE / 2, 0, Math.PI * 2);
    ctx.clip();
    ctx.drawImage(img, cx + offset.x * ratio - drawW / 2, cy + offset.y * ratio - drawH / 2, drawW, drawH);
    ctx.restore();
    offscreen.toBlob(blob => { if (blob) onConfirm(blob); }, "image/jpeg", 0.92);
  };

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={onCancel}
    >
      <div
        className="mx-4 w-full max-w-xs rounded-xl border border-surface-border bg-surface-card p-6 shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <h2 className="mb-1 text-sm font-semibold text-ink-primary">Position Photo</h2>
        <p className="mb-4 text-[11px] text-ink-muted">Drag to reposition · Scroll or use slider to zoom</p>

        <div className="flex justify-center mb-4">
          <canvas
            ref={canvasRef}
            width={CROP_PREVIEW_SIZE}
            height={CROP_PREVIEW_SIZE}
            className="rounded-full cursor-grab active:cursor-grabbing ring-2 ring-surface-border select-none"
            style={{ width: CROP_PREVIEW_SIZE, height: CROP_PREVIEW_SIZE }}
            onMouseDown={handleMouseDown}
            onMouseMove={handleMouseMove}
            onMouseUp={handleMouseUp}
            onMouseLeave={handleMouseUp}
            onWheel={handleWheel}
          />
        </div>

        <div className="mb-5 flex items-center gap-2">
          <span className="text-[11px] text-ink-muted select-none">−</span>
          <input
            type="range"
            min={50}
            max={400}
            value={Math.round(scale * 100)}
            onChange={e => setScale(Number(e.target.value) / 100)}
            className="flex-1 accent-accent"
          />
          <span className="text-[11px] text-ink-muted select-none">+</span>
        </div>

        <div className="flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded-md border border-surface-border px-4 py-2 text-xs text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary"
          >
            Cancel
          </button>
          <button
            onClick={handleConfirm}
            className="rounded-md bg-accent px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-accent-hover"
          >
            Save
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

// ── Avatar ────────────────────────────────────────────────────────────────────
function Avatar({
  character,
  bookFilter,
  size = "lg",
  onUploaded,
}: {
  character: CharacterSummary;
  bookFilter: string | null;
  size?: "sm" | "lg";
  onUploaded?: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const { showToast } = useAppStore();
  const color = nameColor(character.name);
  const initials = character.name
    .split(" ")
    .filter((_, i, a) => i === 0 || i === a.length - 1)
    .map((w) => w[0])
    .join("")
    .toUpperCase();
  const [cropFile, setCropFile] = useState<File | null>(null);

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setCropFile(file);
    e.target.value = "";
  };

  const handleCropConfirm = async (blob: Blob) => {
    setCropFile(null);
    const file = new File([blob], "photo.jpg", { type: "image/jpeg" });
    try {
      await uploadCharacterPhoto(character.id, file, bookFilter ?? undefined);
      showToast("Photo uploaded.");
      onUploaded?.();
    } catch {
      showToast("Failed to upload photo.");
    }
  };

  const sizeClass = size === "lg" ? "h-16 w-16 text-lg" : "h-10 w-10 text-sm";

  return (
    <>
      <div className={clsx("group relative flex-shrink-0 rounded-full overflow-hidden cursor-pointer", sizeClass)} onClick={(e) => { e.stopPropagation(); inputRef.current?.click(); }}>
        {character.photo_url ? (
          <img
            src={character.photo_url}
            alt={character.name}
            className="h-full w-full object-cover"
          />
        ) : (
          <div
            className={clsx(
              "flex h-full w-full items-center justify-center font-semibold",
              color.bg, color.text
            )}
          >
            {initials}
          </div>
        )}
        <button
          onClick={(e) => { e.stopPropagation(); inputRef.current?.click(); }}
          className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity"
          title="Upload photo"
        >
          <Camera className="h-4 w-4 text-white" />
        </button>
        <input ref={inputRef} type="file" accept="image/*" className="hidden" onChange={handleFile} />
      </div>
      {cropFile && (
        <PhotoCropModal
          file={cropFile}
          onConfirm={handleCropConfirm}
          onCancel={() => setCropFile(null)}
        />
      )}
    </>
  );
}

// ── Character card ────────────────────────────────────────────────────────────
function AliasPills({ aliases, onAliasClick }: { aliases: AliasWithProvenance[]; onAliasClick: (alias: AliasWithProvenance) => void }) {
  if (!aliases.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-2">
      {aliases.map((a) =>
        a.book != null ? (
          <button
            key={a.alias}
            onClick={(e) => { e.stopPropagation(); onAliasClick(a); }}
            className="inline-flex items-center gap-1.5 rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-[10px] text-accent hover:bg-accent/20 transition-colors cursor-pointer"
            title={`First seen in ${a.book}, ch. ${a.chapter}`}
          >
            {a.alias}{a.count != null && a.count > 0 && <span className="rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-surface-border text-ink-muted">{a.count}</span>}
          </button>
        ) : (
          <span
            key={a.alias}
            className="inline-flex items-center gap-1.5 rounded-full border border-surface-border px-2 py-0.5 text-[10px] text-ink-muted cursor-default"
          >
            {a.alias}{a.count != null && a.count > 0 && <span className="rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-surface-border text-ink-muted">{a.count}</span>}
          </span>
        )
      )}
    </div>
  );
}

function CharacterCard({
  character,
  bookFilter,
  active,
  onSelect,
  onRelationshipClick,
  onUploaded,
  onAliasClick,
  photoMap,
  disabledIds = new Set(),
  hiddenIds,
  onToggleHidden,
  onEdit,
}: {
  character: CharacterSummary;
  bookFilter: string | null;
  active: boolean;
  onSelect: (id: string) => void;
  onRelationshipClick: (id: string, targetName: string) => void;
  onUploaded: () => void;
  onAliasClick: (alias: AliasWithProvenance) => void;
  photoMap: Record<string, string | null>;
  disabledIds?: Set<string>;
  hiddenIds?: Set<string>;
  onToggleHidden?: (name: string) => void;
  onEdit?: () => void;
}) {
  const visibleRels = character.relationships.filter(r => !hiddenIds?.has(r.character_id));
  const hasRelationships = visibleRels.length > 0;
  const isDisabled = disabledIds.has(character.id);
  const [relSort, setRelSort] = useState<RelSort>("appearances");
  const cycleRelSort = () => setRelSort(s => REL_SORT_CYCLE[(REL_SORT_CYCLE.indexOf(s) + 1) % REL_SORT_CYCLE.length]);
  return (
    <div
      className={clsx(
        "group/card relative flex flex-col rounded-xl border p-4 transition-colors",
        hasRelationships ? "gap-3" : "h-[82px] justify-center overflow-hidden",
        character.hidden
          ? "border-dashed border-ink-muted/30 bg-surface-card opacity-40"
          : isDisabled
            ? "border-surface-border bg-surface-card cursor-not-allowed"
            : active
              ? "border-accent bg-accent/5 cursor-pointer"
              : "border-surface-border bg-surface-card hover:border-accent/40 cursor-pointer"
      )}
      onClick={isDisabled || character.hidden ? undefined : () => onSelect(character.id)}
    >
      {/* Hide / unhide eyeball */}
      {onToggleHidden && (
        <button
          onClick={(e) => { e.stopPropagation(); onToggleHidden(character.name); }}
          title={character.hidden ? "Unhide character" : "Hide character"}
          className={clsx(
            "absolute top-2 right-2 z-10 p-1 rounded text-ink-muted hover:text-ink-primary hover:bg-surface-hover transition-opacity",
            character.hidden ? "opacity-100" : "opacity-0 group-hover/card:opacity-100"
          )}
        >
          {character.hidden ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
        </button>
      )}

      {/* Server-side hidden badge */}
      {character.hidden && (
        <span className="absolute top-1 left-1 px-1.5 py-0.5 bg-surface-hover text-ink-muted text-xs rounded z-10">
          Hidden
        </span>
      )}

      {/* Top row: avatar + name block */}
      <div className={clsx("flex gap-3", hasRelationships ? "items-start" : "items-center")}>
        <Avatar
          character={character}
          bookFilter={bookFilter}
          size={hasRelationships ? "lg" : "sm"}
          onUploaded={onUploaded}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <p className="text-sm font-semibold text-ink-primary leading-tight">{character.name}</p>
            {onEdit && (
              <button
                onClick={(e) => { e.stopPropagation(); onEdit(); }}
                title="Edit character"
                className="opacity-0 group-hover/card:opacity-100 transition-opacity p-0.5 rounded text-ink-muted hover:text-ink-primary hover:bg-surface-hover flex-shrink-0"
              >
                <Pencil className="h-3 w-3" />
              </button>
            )}
          </div>
          {character.aliases.length > 0 && (
            <AliasPills aliases={character.aliases} onAliasClick={onAliasClick} />
          )}
        </div>
      </div>

      {/* Relationships */}
      {visibleRels.length > 0 && (
        <div onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between mb-1.5">
            <p className="text-[10px] font-bold uppercase tracking-widest text-ink-primary pl-2">
              Relationships ({visibleRels.length}){" "}
              <button onClick={(e) => { e.stopPropagation(); cycleRelSort(); }} className="font-normal normal-case tracking-normal text-ink-muted/50 hover:text-ink-muted transition-colors">{REL_SORT_LABEL[relSort]}</button>
            </p>
            <p className="text-[10px] text-ink-muted/60 italic pr-2">Click on a relationship to view insights</p>
          </div>
          <div className="divide-y divide-surface-border rounded-lg border border-surface-border overflow-y-auto h-[140px]">
            {sortRels(visibleRels, relSort).map((rel) => {
              const c = nameColor(rel.target);
              const initials = rel.target
                .split(" ")
                .filter((_, i, a) => i === 0 || i === a.length - 1)
                .map((w) => w[0])
                .join("")
                .toUpperCase();
              const label = (rel.gendered_status || rel.status || "").split(";")[0].trim();
              const relDisabled = disabledIds.has(rel.character_id);
              const RowEl = relDisabled ? "div" : "button";
              return (
                <RowEl
                  key={rel.target}
                  {...(!relDisabled && { onClick: () => onRelationshipClick(rel.character_id, rel.target) })}
                  className={clsx("w-full flex items-center gap-2 px-2.5 py-2 text-left transition-colors", relDisabled ? "cursor-not-allowed" : "hover:bg-surface-hover")}
                >
                  <div className="flex-shrink-0 h-6 w-6 rounded-full overflow-hidden">
                    {(rel.photo_url ?? photoMap[rel.character_id] ?? photoMap[rel.target.split(" ")[0].toLowerCase()]) ? (
                      <img src={(rel.photo_url ?? photoMap[rel.character_id] ?? photoMap[rel.target.split(" ")[0].toLowerCase()])!} alt={rel.target} className="h-full w-full object-cover" />
                    ) : (
                      <div className={clsx("h-full w-full flex items-center justify-center text-[9px] font-semibold", c.bg, c.text)}>
                        {initials}
                      </div>
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="text-[11px] font-medium text-ink-primary">{rel.target}</span>
                    {label && (
                      <span className="ml-1 text-[10px] italic text-ink-muted">({label})</span>
                    )}
                  </div>
                  {!relDisabled && <ChevronRight className="flex-shrink-0 h-3 w-3 text-ink-muted/40" />}
                </RowEl>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// ── Detail panel ──────────────────────────────────────────────────────────────
function DetailPanel({
  characterId,
  bookFilter,
  onClose,
  onRelationshipClick,
  onUploaded,
  onAliasClick,
  onArcSourceClick,
  onKnowledgeSourceClick,
  onChapterClick,
  photoMap = {},
  disabledIds = new Set(),
  hiddenIds,
}: {
  characterId: string;
  bookFilter: string | null;
  onClose: () => void;
  onRelationshipClick: (id: string, targetName: string) => void;
  onUploaded: () => void;
  onAliasClick: (alias: AliasWithProvenance) => void;
  onArcSourceClick?: (entry: ArcEntry, book: string) => void;
  onKnowledgeSourceClick?: (item: KnowledgeItem) => void;
  onChapterClick?: (chapter: number) => void;
  photoMap?: Record<string, string | null>;
  disabledIds?: Set<string>;
  hiddenIds?: Set<string>;
}) {
  const books = useAppStore((s) => s.books);
  const bookOrder = books.map((b) => b.name);
  const [detail, setDetail] = useState<CharacterDetail | null>(null);
  const [bookDetail, setBookDetail] = useState<CharacterBookDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [relSort, setRelSort] = useState<RelSort>("appearances");
  const cycleRelSort = () => setRelSort(s => REL_SORT_CYCLE[(REL_SORT_CYCLE.indexOf(s) + 1) % REL_SORT_CYCLE.length]);

  useEffect(() => {
    setLoading(true);
    setDetail(null);
    setBookDetail(null);

    const fetchAll = async () => {
      const d = await fetchCharacterDetail(characterId, bookFilter ?? undefined);
      setDetail(d);
      if (bookFilter) {
        try {
          const bd = await fetchCharacterBookDetail(characterId, bookFilter);
          setBookDetail(bd);
        } catch {
          // No book-level data for this character; that's fine
        }
      }
      setLoading(false);
    };
    fetchAll().catch(() => setLoading(false));
  }, [characterId, bookFilter]);

  return (
    <div className="flex h-full flex-col overflow-hidden border-l border-t border-surface-border bg-surface-card rounded-tl-lg">
      {/* Header */}
      <div className="relative flex-shrink-0 flex items-start gap-3 px-5 pt-6 pb-3 border-b border-surface-border">
        {detail && (
          <Avatar
            character={detail}
            bookFilter={bookFilter}
            size="lg"
            onUploaded={onUploaded}
          />
        )}
        <div className="flex-1 min-w-0 pr-6">
          {loading ? (
            <div className="h-4 w-32 animate-pulse rounded bg-surface-border" />
          ) : (
            <>
              <p className="text-sm font-semibold text-ink-primary leading-tight">{detail?.name}</p>
              {detail?.aliases && detail.aliases.length > 0 && (
                <AliasPills aliases={detail.aliases} onAliasClick={onAliasClick} />
              )}
            </>
          )}
        </div>
        <button
          onClick={onClose}
          className="absolute top-4 right-4 rounded p-1 text-ink-muted/50 hover:text-ink-secondary transition-colors"
          title="Close"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-5">
        {loading ? (
          <div className="space-y-2">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="h-3 animate-pulse rounded bg-surface-border" style={{ width: `${60 + (i % 3) * 15}%` }} />
            ))}
          </div>
        ) : (
          <>
            {/* Relationships */}
            {(bookDetail?.relationships ?? detail?.relationships ?? []).filter(r => !hiddenIds?.has(r.character_id)).length > 0 && (() => {
              const rels = (bookDetail?.relationships ?? detail?.relationships ?? []).filter(r => !hiddenIds?.has(r.character_id));
              return (
                <div className="mb-4">
                  <div className="flex items-center justify-between mb-2">
                    <p className="text-[11px] font-bold uppercase tracking-widest text-ink-primary">
                      Core Relationships ({rels.length}){" "}
                      <button onClick={cycleRelSort} className="font-normal normal-case tracking-normal text-ink-muted/50 hover:text-ink-muted transition-colors">{REL_SORT_LABEL[relSort]}</button>
                    </p>
                    <p className="text-[10px] text-ink-muted/60 italic">Click on a relationship to view insights</p>
                  </div>
                  <div className="divide-y divide-surface-border rounded-lg border border-surface-border overflow-y-auto h-[140px]">
                    {sortRels(rels, relSort).map((rel) => {
                      const c = nameColor(rel.target);
                      const initials = rel.target
                        .split(" ")
                        .filter((_, i, a) => i === 0 || i === a.length - 1)
                        .map((w) => w[0])
                        .join("")
                        .toUpperCase();
                      const photo = rel.photo_url ?? photoMap[rel.character_id] ?? photoMap[rel.target.split(" ")[0].toLowerCase()];
                      const relDisabled = disabledIds.has(rel.character_id);
                      const RowEl = relDisabled ? "div" : "button";
                      return (
                        <RowEl
                          key={rel.target}
                          {...(!relDisabled && { onClick: () => onRelationshipClick(rel.character_id, rel.target) })}
                          className={clsx("w-full flex items-center gap-3 px-3 py-2.5 text-left transition-colors", relDisabled ? "cursor-not-allowed" : "hover:bg-surface-hover")}
                        >
                          <div className={clsx("flex-shrink-0 h-7 w-7 rounded-full overflow-hidden flex items-center justify-center text-[10px] font-semibold", c.bg, c.text)}>
                            {photo ? (
                              <img src={photo} alt={rel.target} className="h-full w-full object-cover" />
                            ) : (
                              initials
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <span className="text-[12px] font-medium text-ink-primary">{rel.target}</span>
                            {(rel.gendered_status || rel.status) && (
                              <span className="ml-1.5 text-[11px] italic text-ink-muted">({rel.gendered_status || rel.status})</span>
                            )}
                          </div>
                          {!relDisabled && <ChevronRight className="flex-shrink-0 h-3.5 w-3.5 text-ink-muted/40" />}
                        </RowEl>
                      );
                    })}
                  </div>
                </div>
              );
            })()}

            {/* Active conflicts (book level) */}
            {bookDetail && bookDetail.active_conflicts.length > 0 && (
              <Section title="Active Conflicts" className="-mt-5">
                <ScrollableList>
                  {bookDetail.active_conflicts.map((c, i) => (
                    <KnowledgeItemRow key={i} item={c} onSourceClick={onKnowledgeSourceClick} />
                  ))}
                </ScrollableList>
              </Section>
            )}

            {/* Knowledge (book level) */}
            {bookDetail && bookDetail.knowledge.length > 0 && (
              <Section title="Knows" className="-mt-5">
                <ScrollableList>
                  {bookDetail.knowledge.map((k, i) => (
                    <KnowledgeItemRow key={i} item={k} onSourceClick={onKnowledgeSourceClick} />
                  ))}
                </ScrollableList>
              </Section>
            )}

            {/* Does not know (book level) */}
            {bookDetail && bookDetail.does_not_know.length > 0 && (
              <Section title="Doesn't Know" className="-mt-5">
                <ScrollableList>
                  {bookDetail.does_not_know.map((k, i) => (
                    <KnowledgeItemRow key={i} item={k} onSourceClick={onKnowledgeSourceClick} />
                  ))}
                </ScrollableList>
              </Section>
            )}

            {/* Arc (series level fallback) */}
            {!bookFilter && detail && (() => {
              const hasArc = detail.arc && Object.keys(detail.arc).some((b) => detail.arc[b]?.length);
              return (
              <Section title="Arc" prominent grow={!hasArc} className="-mt-5">
                {hasArc ? (
                  <div className="space-y-4">
                    {bookOrder.filter((b) => detail.arc[b]?.length).map((b) => (
                      <div key={b}>
                        <p className="text-[10px] font-semibold uppercase tracking-widest text-ink-primary mb-2">{b}</p>
                        <ArcBookInsights
                          book={b}
                          entries={detail.arc[b]!}
                          onSourceClick={onArcSourceClick}
                        />
                      </div>
                    ))}
                  </div>
                ) : (() => {
                  const TITLES = new Set(['mr.', 'mrs.', 'ms.', 'miss', 'dr.', 'prof.', 'sir', 'lord', 'lady']);
                  const first = detail.name.split(' ')[0];
                  const displayName = TITLES.has(first.toLowerCase()) ? detail.name : first;
                  return (
                    <div className="flex-1 flex items-center justify-center">
                      <div className="flex flex-col items-center gap-3 text-center">
                        <Sparkles className="h-8 w-8 text-ink-muted/30" strokeWidth={1.5} />
                        <div>
                          <p className="text-[11px] font-medium text-ink-secondary">No arc insights were found for {displayName}</p>
                          <p className="mt-0.5 text-[10px] text-ink-muted leading-relaxed">If you think this is a mistake, consider re-running your pipeline</p>
                        </div>
                      </div>
                    </div>
                  );
                })()}
              </Section>
              );
            })()}

            {/* Chapter appearances (book level) */}
            {bookDetail && bookDetail.chapter_appearances.length > 0 && (
              <Section title="Appears in Chapter(s)" className="-mt-5">
                <div className="flex flex-wrap gap-2">
                  {bookDetail.chapter_appearances.map((ch) => (
                    <button
                      key={ch}
                      onClick={() => onChapterClick?.(ch)}
                      className="rounded bg-accent-subtle px-1.5 py-0.5 text-[10px] font-medium text-accent hover:bg-accent/20 transition-colors"
                    >
                      {chapterLabel(ch)}
                    </button>
                  ))}
                </div>
              </Section>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function KnowledgeItemRow({ item, onSourceClick }: { item: KnowledgeItem; onSourceClick?: (item: KnowledgeItem) => void }) {
  return (
    <div className="group flex items-start gap-2">
      {item.first_revealed_chapter != null && (
        <span className="mt-0.5 flex-shrink-0 rounded bg-accent-subtle px-1.5 py-0.5 text-[10px] font-medium text-accent">
          {chapterLabel(item.first_revealed_chapter)}
        </span>
      )}
      <p className="flex-1 text-[11px] text-ink-secondary leading-relaxed">{item.text}</p>
      {item.source_quote && onSourceClick && (
        <button
          onClick={() => onSourceClick(item)}
          title="View source passage"
          className="mt-0.5 flex-shrink-0 text-ink-muted/50 hover:text-accent transition-colors opacity-0 group-hover:opacity-100"
        >
          <Link className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}

function ScrollableList({ children }: { children: React.ReactNode }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [showGradient, setShowGradient] = useState(false);
  const [atBottom, setAtBottom] = useState(false);

  const checkOverflow = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const hasOverflow = el.scrollHeight > el.clientHeight;
    const reachedBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 4;
    setShowGradient(hasOverflow && !reachedBottom);
    setAtBottom(hasOverflow && reachedBottom);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(checkOverflow);
    ro.observe(el);
    return () => ro.disconnect();
  }, [checkOverflow]);

  return (
    <div>
      <div className="relative">
        <div
          ref={scrollRef}
          onScroll={checkOverflow}
          className="space-y-2.5 max-h-[33vh] overflow-y-auto pr-1"
        >
          {children}
        </div>
        {showGradient && (
          <div className="pointer-events-none absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-surface-card to-transparent" />
        )}
      </div>
      <button
        onClick={() => scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" })}
        className={clsx("mt-1.5 w-full text-center text-[10px] text-ink-muted/60 hover:text-ink-muted transition-colors", atBottom ? "visible" : "invisible")}
      >
        scroll back to top
      </button>
    </div>
  );
}

function ArcEntryRow({ entry, onSourceClick }: { entry: ArcEntry; onSourceClick?: (entry: ArcEntry) => void }) {
  return (
    <div className="group flex items-start gap-2">
      {/* no chapter badge: arc insights are book-level summaries — the
          backend's chapter field is a 0 placeholder, not a real chapter */}
      <p className="flex-1 text-[11px] text-ink-secondary leading-relaxed">{entry.insight}</p>
      {entry.source_quote && onSourceClick && (
        <button
          onClick={() => onSourceClick(entry)}
          title="View source passage"
          className="mt-0.5 flex-shrink-0 text-ink-muted/50 hover:text-accent transition-colors opacity-0 group-hover:opacity-100"
        >
          <Link className="h-3 w-3" />
        </button>
      )}
    </div>
  );
}

function ArcBookInsights({ book, entries, onSourceClick }: {
  book: string;
  entries: ArcEntry[];
  onSourceClick?: (entry: ArcEntry, book: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [showGradient, setShowGradient] = useState(false);
  const [atBottom, setAtBottom] = useState(false);

  const checkOverflow = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const hasOverflow = el.scrollHeight > el.clientHeight;
    const reachedBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 4;
    setShowGradient(hasOverflow && !reachedBottom);
    setAtBottom(hasOverflow && reachedBottom);
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const ro = new ResizeObserver(checkOverflow);
    ro.observe(el);
    return () => ro.disconnect();
  }, [checkOverflow]);

  return (
    <div>
      <div className="relative">
        <div
          ref={scrollRef}
          onScroll={checkOverflow}
          className="space-y-2.5 max-h-[25vh] overflow-y-auto pr-1"
        >
          {entries.map((entry, i) => (
            <ArcEntryRow
              key={i}
              entry={entry}
              onSourceClick={onSourceClick ? (e) => onSourceClick(e, book) : undefined}
            />
          ))}
        </div>
        {showGradient && (
          <div className="pointer-events-none absolute bottom-0 left-0 right-0 h-8 bg-gradient-to-t from-surface-card to-transparent" />
        )}
      </div>
      <button
        onClick={() => scrollRef.current?.scrollTo({ top: 0, behavior: "smooth" })}
        className={clsx("mt-1.5 w-full text-center text-[10px] text-ink-muted/60 hover:text-ink-muted transition-colors", atBottom ? "visible" : "invisible")}
      >
        scroll back to top
      </button>
    </div>
  );
}

function Section({ title, children, prominent, grow, className }: { title: string; children: React.ReactNode; prominent?: boolean; grow?: boolean; className?: string }) {
  return (
    <div className={clsx(grow ? "flex flex-col flex-1 min-h-0" : undefined, className)}>
      <p className={prominent
        ? "mb-1.5 text-[11px] font-bold uppercase tracking-widest text-ink-primary"
        : "mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-ink-primary"
      }>{title}</p>
      {children}
    </div>
  );
}

// ── Main pane ─────────────────────────────────────────────────────────────────
export default function CharactersPane() {
  const { showToast, setActivePane, setPendingPipelineBook, books } = useAppStore();
  const bookOrder = books.map((b) => b.name);
  const [characters, setCharacters] = useState<CharacterSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [bookFilter, setBookFilter] = useState<string | null>(null);
  const [showHidden, setShowHidden] = useState(false);
  const [countMap, setCountMap] = useState<Record<string, number>>({});
  const [search, setSearch] = useState(
    () => new URLSearchParams(window.location.search).get("search") ?? ""
  );
  const [editingCharacter, setEditingCharacter] = useState<CharacterSummary | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [viewerOpen, setViewerOpen] = useState(false);
  const [viewerHasBack, setViewerHasBack] = useState(false);
  const [activeCitation, setActiveCitation] = useState<Citation | null>(null);
  const [activeBookId, setActiveBookId] = useState<string>("");
  const [lightMode, setLightMode] = useState(() => useAppStore.getState().appSettings?.viewer_light_mode ?? true);
  const cardRefs = useRef<Record<string, HTMLDivElement | null>>({});
  // server-side hidden (writer_data) — survives re-ingests and browsers
  const hiddenIds = new Set(characters.filter(c => c.hidden).map(c => c.id));
  const knownCharacterIds = new Set(characters.map(c => c.id));
  const disabledIds = new Set([
    ...characters.filter(c => c.relationships.length === 0).map(c => c.id),
    ...characters.flatMap(c => c.relationships.map(r => r.character_id)).filter(id => !knownCharacterIds.has(id)),
  ]);
  const bookHasNoData = bookFilter !== null && !(countMap[bookFilter] > 0);
  const bookFilterLabel = bookFilter ? (bookOrder.find(b => bookId(b) === bookFilter) ?? bookFilter) : null;

  const load = useCallback(async (filter: string | null) => {
    setLoading(true);
    try {
      // always fetch hidden too; visibility is a client-side toggle
      const data = await fetchCharacters(filter ?? undefined, { includeHidden: true });
      setCharacters(data);
      if (!filter) {
        const visible = data.filter((c) => !c.hidden);
        const map: Record<string, number> = { all: visible.length };
        for (const c of visible) {
          for (const b of c.books) {
            const bid = bookId(b);
            map[bid] = (map[bid] ?? 0) + 1;
          }
        }
        setCountMap(map);
      }
    } catch {
      setCharacters([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(bookFilter);
  }, [bookFilter, load]);

  // Sync search to URL; clear on unmount (when user leaves the tab)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    if (search) {
      params.set("search", search);
    } else {
      params.delete("search");
    }
    history.replaceState(null, "", "?" + params.toString());
    return () => {
      const p = new URLSearchParams(window.location.search);
      p.delete("search");
      history.replaceState(null, "", "?" + p.toString());
    };
  }, [search]);

  const handleSelect = (id: string) => {
    if (activeId === id && panelOpen) {
      setPanelOpen(false);
      setTimeout(() => setActiveId(null), 300);
    } else {
      setActiveId(id);
      setPanelOpen(true);
      setViewerOpen(false);
    }
  };

  const handleRelationshipClick = (relCharacterId: string, relTargetName: string) => {
    // Resolve to an actual card ID — try direct match first, then first-name match
    const firstName = relTargetName.split(" ")[0].toLowerCase();
    const resolvedId =
      cardRefs.current[relCharacterId] != null
        ? relCharacterId
        : characters.find(c => c.name.split(" ")[0].toLowerCase() === firstName)?.id ?? relCharacterId;

    setActiveId(resolvedId);
    setPanelOpen(true);
    setViewerOpen(false);
    setTimeout(() => {
      cardRefs.current[resolvedId]?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
  };

  const handleClose = () => {
    setPanelOpen(false);
    setViewerOpen(false);
    setTimeout(() => setActiveId(null), 300);
  };

  const handleAliasClick = (alias: AliasWithProvenance) => {
    if (alias.book == null || alias.chapter == null) return;
    const citation: Citation = {
      book: alias.book,
      chapter: alias.chapter,
      chapter_heading: String(alias.chapter),
      pov: "",
      date: null,
      chunk_index: 0,
      snippet: alias.context ?? alias.alias,
      distance: 0,
    };
    setActiveCitation(citation);
    setActiveBookId(alias.book.toLowerCase().replace(/'/g, "").replace(/ /g, "-"));
    setViewerHasBack(false);
    setViewerOpen(true);
    setPanelOpen(false);
    setTimeout(() => setActiveId(null), 300);
  };

  const handleArcSourceClick = (entry: ArcEntry, book: string) => {
    if (!entry.source_quote) return;
    const citation: Citation = {
      book,
      chapter: entry.chapter,
      chapter_heading: String(entry.chapter),
      pov: "",
      date: null,
      chunk_index: 0,
      snippet: entry.source_quote,
      distance: 0,
    };
    setActiveCitation(citation);
    setActiveBookId(book.toLowerCase().replace(/'/g, "").replace(/ /g, "-"));
    setViewerHasBack(true);
    setViewerOpen(true);
    setPanelOpen(false);
    // Keep activeId alive so the back button can re-open the panel
  };

  const handleChapterClick = (chapter: number) => {
    if (!bookFilterLabel) return;
    const citation: Citation = {
      book: String(bookFilterLabel),
      chapter,
      chapter_heading: String(chapter),
      pov: "",
      date: null,
      chunk_index: 0,
      snippet: "",
      distance: 0,
    };
    setActiveCitation(citation);
    setActiveBookId(bookFilter ?? "");
    setViewerHasBack(true);
    setViewerOpen(true);
    setPanelOpen(false);
  };

  const handleKnowledgeSourceClick = (item: KnowledgeItem) => {
    if (!item.source_quote || !bookFilterLabel || item.first_revealed_chapter == null) return;
    const citation: Citation = {
      book: String(bookFilterLabel),
      chapter: item.first_revealed_chapter,
      chapter_heading: String(item.first_revealed_chapter),
      pov: "",
      date: null,
      chunk_index: 0,
      snippet: item.source_quote,
      distance: 0,
    };
    setActiveCitation(citation);
    setActiveBookId(bookFilter ?? "");
    setViewerHasBack(true);
    setViewerOpen(true);
    setPanelOpen(false);
  };

  const handleViewerBack = () => {
    setViewerOpen(false);
    setViewerHasBack(false);
    setPanelOpen(true);
  };

  useEffect(() => {
    if (!viewerOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (viewerHasBack) {
          handleViewerBack();
        } else {
          setViewerOpen(false);
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [viewerOpen, viewerHasBack]);

  const handleToggleHidden = useCallback(async (name: string) => {
    const char = characters.find((c) => c.name === name);
    try {
      if (char?.hidden) {
        await unhideCharacter(name);
        showToast(`${name} is visible again.`);
      } else {
        await hideCharacter(name);
        showToast(`${name} hidden. Toggle "Hidden" above to see hidden characters.`);
      }
      await load(bookFilter);
    } catch {
      showToast("Failed to update character visibility.");
    }
  }, [characters, bookFilter, load, showToast]);

  const handleExtractConfirm = async () => {
    setConfirmOpen(false);
    try {
      await triggerExtract();
      showToast("Re-extraction started — this may take several minutes.");
    } catch {
      showToast("Failed to start re-extraction.");
    }
  };

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 px-6 pt-4 pb-3">
        <div className="flex items-center gap-2">
          <Users className="h-6 w-6 flex-shrink-0 text-accent" />
          <div>
            <div className="flex items-center gap-1">
              <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">Characters</p>
              <div className="group relative">
                <Info className="h-3.5 w-3.5 text-ink-muted hover:text-ink-secondary transition-colors cursor-default" />
                <div className="pointer-events-none absolute left-0 top-5 z-50 w-72 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-[11px] leading-relaxed text-ink-muted shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                  Character profiles are built by AI as it reads each chapter — extracting names, relationships, knowledge, and conflicts for every POV character across the series. Insights update when you re-extract.
                </div>
              </div>
            </div>
            <p className="mt-0.5 text-[11px] text-ink-muted">
              Click a character to view their profile. Select a book for book-level insights.
            </p>
          </div>
        </div>
        <div className="mt-3 border-t border-surface-border" />
      </div>

      {/* Book filter tabs */}
      <div className="flex-shrink-0 flex items-center gap-2 px-6 pt-1 pb-3">
        <div className="flex flex-1 items-center gap-1 overflow-x-auto scrollbar-hide">
          {[{ id: null, label: "All Books" }, ...bookOrder.map((b) => ({ id: bookId(b), label: b }))].map(
            ({ id, label }) => {
              const count = id === null ? countMap.all : countMap[id];
              return (
                <button
                  key={id ?? "all"}
                  onClick={() => { setBookFilter(id); setActiveId(null); setActiveCitation(null); setPanelOpen(false); setViewerOpen(false); }}
                  className={clsx(
                    "flex-shrink-0 flex items-center gap-1.5 rounded-full px-3 py-1 text-xs transition-colors",
                    bookFilter === id
                      ? "bg-accent/20 text-accent ring-1 ring-accent/40"
                      : "text-ink-secondary hover:bg-surface-hover"
                  )}
                >
                  {label}
                  {count != null && (
                    <span className={clsx(
                      "rounded-full px-1.5 py-0.5 text-[10px] font-medium",
                      bookFilter === id
                        ? "bg-accent/20 text-accent"
                        : "bg-surface-border text-ink-muted"
                    )}>
                      {count}
                    </span>
                  )}
                </button>
              );
            }
          )}
        </div>
        <button
          onClick={() => setShowHidden((v) => !v)}
          title={showHidden ? "Hide hidden characters" : "Show hidden characters"}
          className={clsx(
            "flex-shrink-0 flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs transition-colors",
            showHidden
              ? "bg-accent/20 text-accent ring-1 ring-accent/40"
              : "bg-surface-card text-ink-secondary hover:text-ink-primary"
          )}
        >
          {showHidden ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
          Hidden ({hiddenIds.size})
        </button>
      </div>


      {/* Search */}
      <div className="flex-shrink-0 px-6 pb-1.5">
        <div className="relative">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-ink-muted" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search character(s)..."
            disabled={loading || bookHasNoData}
            className="w-full rounded-md border border-surface-border bg-surface py-1.5 pl-8 pr-3 text-xs text-ink-primary placeholder:text-ink-muted focus:border-accent focus:outline-none transition-colors disabled:cursor-not-allowed disabled:opacity-40"
          />
        </div>
      </div>

      {/* Body */}
      <div className="flex flex-1 min-h-0">
        {/* Character grid */}
        <div
          className={clsx(
            "flex flex-col min-h-0 transition-[width] duration-300 ease-in-out overflow-hidden",
            panelOpen || viewerOpen ? "w-2/3" : "w-full"
          )}
        >
          <div className="flex flex-1 flex-col overflow-y-auto px-6 pb-6 [scrollbar-gutter:stable]">
            {loading ? (
              <div className="grid grid-cols-3 gap-3 pt-2">
                {[...Array(9)].map((_, i) => (
                  <div key={i} className="animate-pulse rounded-xl border border-surface-border bg-surface-card p-4 flex flex-col gap-3">
                    {/* Avatar + name row */}
                    <div className="flex gap-3 items-start">
                      <div className="h-16 w-16 flex-shrink-0 rounded-full bg-surface-border" />
                      <div className="flex-1 min-w-0 pt-1 space-y-2">
                        <div className="h-3.5 w-3/4 rounded bg-surface-border" />
                        <div className="h-2.5 w-1/2 rounded bg-surface-border/60" />
                      </div>
                    </div>
                    {/* Relationships block */}
                    <div className="rounded-lg border border-surface-border h-[140px] overflow-hidden">
                      {[...Array(4)].map((_, j) => (
                        <div key={j} className="flex items-center gap-2 px-2.5 py-2 border-b border-surface-border last:border-0">
                          <div className="h-6 w-6 flex-shrink-0 rounded-full bg-surface-border" />
                          <div className="flex-1 space-y-1.5">
                            <div className="h-2.5 w-2/3 rounded bg-surface-border" />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            ) : bookHasNoData ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
                <Users className="h-8 w-8 text-ink-muted/40" strokeWidth={1.5} />
                <div>
                  <p className="text-sm font-medium text-ink-secondary">{bookFilterLabel} Has No Character Data</p>
                  <p className="mt-0.5 text-[11px] text-ink-muted">Run the pipeline to extract insights</p>
                  <button
                    onClick={() => { setPendingPipelineBook(bookFilter); setActivePane("pipeline"); }}
                    className="mt-3 rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:bg-accent-hover transition-colors"
                  >
                    Run Pipeline
                  </button>
                </div>
              </div>
            ) : characters.length === 0 ? (
              <div className="flex flex-1 flex-col items-center justify-center gap-3 text-center">
                <Users className="h-8 w-8 text-ink-muted/40" strokeWidth={1.5} />
                <p className="text-sm text-ink-muted">No character data found.</p>
              </div>
            ) : (() => {
              const filtered = characters.filter((char) => {
                if (hiddenIds.has(char.id) && !showHidden) return false;
                if (!search.trim()) return true;
                const q = search.toLowerCase();
                return char.name.toLowerCase().includes(q);
              });
              if (filtered.length === 0 && search.trim()) {
                return (
                  <div className="flex flex-1 h-full items-center justify-center">
                    <div className="flex flex-col items-center gap-3 text-center w-[250px]">
                      <Users className="h-8 w-8 text-ink-muted/40" strokeWidth={1.5} />
                      <div>
                        <p className="text-sm font-medium text-ink-primary">No characters matched "{search}"</p>
                        <p className="mt-1 text-[11px] text-ink-muted leading-relaxed">
                          If you expect to see this character, consider re-running your book through the pipeline with a better AI model
                        </p>
                      </div>
                    </div>
                  </div>
                );
              }
              const pm = {
                ...Object.fromEntries(characters.map(c => [c.id, c.photo_url])),
                ...Object.fromEntries(characters.map(c => [c.name.split(" ")[0].toLowerCase(), c.photo_url])),
              };
              const cols = panelOpen || viewerOpen ? 2 : 3;
              // Shortest-column-first masonry: assign each card to the column
              // with the least estimated height so tall and short cards balance evenly.
              const GAP = 12; // gap-3 = 12px
              const TALL_H = 250; // card with visible relationships
              const SHORT_H = 82; // card without (h-[82px])
              const effectiveHiddenIds = showHidden ? new Set<string>() : hiddenIds;
              const colHeights = Array<number>(cols).fill(0);
              const colArrays: CharacterSummary[][] = Array.from({ length: cols }, () => []);
              for (const char of filtered) {
                const hasVis = char.relationships.some(r => !effectiveHiddenIds.has(r.character_id));
                const h = (hasVis ? TALL_H : SHORT_H) + GAP;
                const shortest = colHeights.indexOf(Math.min(...colHeights));
                colArrays[shortest].push(char);
                colHeights[shortest] += h;
              }
              const renderCard = (char: CharacterSummary) => (
                <div key={char.id} ref={(el) => { cardRefs.current[char.id] = el; }}>
                  <CharacterCard
                    character={char}
                    bookFilter={bookFilter}
                    active={char.id === activeId}
                    onSelect={handleSelect}
                    onRelationshipClick={handleRelationshipClick}
                    onUploaded={() => load(bookFilter)}
                    onAliasClick={handleAliasClick}
                    photoMap={pm}
                    disabledIds={disabledIds}
                    hiddenIds={effectiveHiddenIds}
                    onToggleHidden={handleToggleHidden}
                    onEdit={() => setEditingCharacter(char)}
                  />
                </div>
              );
              return (
                <div className="flex gap-3 pt-2 items-start">
                  {colArrays.map((col, c) => (
                    <div key={c} className="flex-1 flex flex-col gap-3">{col.map(renderCard)}</div>
                  ))}
                </div>
              );
            })()}
          </div>

          {/* Footer */}
          <div className="flex-shrink-0 border-t border-surface-border bg-surface-card p-4">
            <button
              onClick={() => setConfirmOpen(true)}
              className="flex w-full items-center justify-center gap-2 rounded-md border border-surface-border bg-surface px-3 py-[13px] text-xs text-ink-secondary hover:border-accent hover:text-accent transition-colors"
            >
              <RefreshCw className="h-3 w-3" />
              Re-Extract Character Data
            </button>
          </div>
        </div>

        {/* Detail panel */}
        <div
          className={clsx(
            "mt-2 transition-[width] duration-300 ease-in-out overflow-hidden",
            panelOpen ? "w-1/3" : "w-0"
          )}
        >
          {activeId && (
            <DetailPanel
              characterId={activeId}
              bookFilter={bookFilter}
              onClose={handleClose}
              onRelationshipClick={handleRelationshipClick}
              onUploaded={() => load(bookFilter)}
              onAliasClick={handleAliasClick}
              onArcSourceClick={handleArcSourceClick}
              onKnowledgeSourceClick={handleKnowledgeSourceClick}
              onChapterClick={handleChapterClick}
              disabledIds={disabledIds}
              hiddenIds={showHidden ? new Set<string>() : hiddenIds}
              photoMap={{
                ...Object.fromEntries(characters.map(c => [c.id, c.photo_url])),
                ...Object.fromEntries(characters.map(c => [c.name.split(" ")[0].toLowerCase(), c.photo_url])),
              }}
            />
          )}
        </div>

        {/* Chapter viewer */}
        <div
          className={clsx(
            "mt-2 transition-[width] duration-300 ease-in-out overflow-hidden",
            viewerOpen ? "w-1/3" : "w-0"
          )}
        >
          {viewerOpen && activeCitation && (
            <ChapterViewer
              citation={activeCitation}
              bookId={activeBookId}
              lightMode={lightMode}
              onToggleLightMode={() => setLightMode(v => !v)}
              onClose={() => { setViewerOpen(false); setViewerHasBack(false); }}
              onBack={viewerHasBack ? handleViewerBack : undefined}
            />
          )}
        </div>
      </div>

      <ConfirmModal
        open={confirmOpen}
        title="Re-extract character data?"
        message="This re-runs the full extraction pipeline across all 5 books, rebuilding character profiles, relationships, aliases, and arc summaries from scratch. It will take several minutes to complete. Existing uploaded photos will not be affected."
        confirmLabel="Re-extract"
        onConfirm={handleExtractConfirm}
        onCancel={() => setConfirmOpen(false)}
      />

      {editingCharacter && (
        <CharacterEditModal
          character={editingCharacter}
          allCharacters={characters}
          onClose={() => setEditingCharacter(null)}
          onSaved={() => {
            load(bookFilter);
            // Re-open with fresh data if character is still selected
          }}
        />
      )}
    </div>
  );
}
