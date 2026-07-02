import { useState, useEffect, useRef, useCallback } from "react";
import { createPortal } from "react-dom";
import { Camera, GitCompare, MessageSquare, Plus, X } from "lucide-react";
import { clsx } from "clsx";
import { useAppStore } from "../../../store/useAppStore";
import { usePlanStore } from "../../../store/usePlanStore";
import { uploadWriterCharacterPhoto } from "../../../api/plan";
import type { WriterCharacter, CharacterCategory } from "../../../types";

const POV_PALETTE = [
  { bg: "bg-rose-500/20",    text: "text-rose-300"    },
  { bg: "bg-sky-500/20",     text: "text-sky-300"     },
  { bg: "bg-violet-500/20",  text: "text-violet-300"  },
  { bg: "bg-amber-500/20",   text: "text-amber-300"   },
  { bg: "bg-teal-500/20",    text: "text-teal-300"    },
  { bg: "bg-fuchsia-500/20", text: "text-fuchsia-300" },
];
function nameColor(name: string) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) & 0xffff;
  return POV_PALETTE[hash % POV_PALETTE.length];
}
function relInitials(name: string) {
  const parts = name.trim().split(/\s+/);
  return (parts.length > 1 ? parts[0][0] + parts[parts.length - 1][0] : parts[0][0]).toUpperCase();
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

  useEffect(() => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { imgRef.current = img; setImgLoaded(true); };
    img.src = url;
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === "Escape") onCancel(); };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onCancel]);

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
    setOffset({ x: dragStart.current.ox + (e.clientX - dragStart.current.mx), y: dragStart.current.oy + (e.clientY - dragStart.current.my) });
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onCancel}>
      <div className="mx-4 w-full max-w-xs rounded-xl border border-surface-border bg-surface-card p-6 shadow-2xl" onClick={e => e.stopPropagation()}>
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
          <input type="range" min={50} max={400} value={Math.round(scale * 100)} onChange={e => setScale(Number(e.target.value) / 100)} className="flex-1 accent-accent" />
          <span className="text-[11px] text-ink-muted select-none">+</span>
        </div>
        <div className="flex justify-end gap-2">
          <button onClick={onCancel} className="rounded-md border border-surface-border px-4 py-2 text-xs text-ink-secondary transition-colors hover:border-accent hover:text-ink-primary">Cancel</button>
          <button onClick={handleConfirm} className="rounded-md bg-accent px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-accent-hover">Save</button>
        </div>
      </div>
    </div>,
    document.body
  );
}

const CATEGORIES: { value: CharacterCategory; label: string }[] = [
  { value: "main",      label: "Main"      },
  { value: "secondary", label: "Secondary" },
  { value: "tertiary",  label: "Tertiary"  },
];

const categoryStyle: Record<CharacterCategory, string> = {
  main:      "bg-accent/15 text-accent border-accent/30",
  secondary: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  tertiary:  "bg-teal-500/15 text-teal-400 border-teal-500/30",
};

interface WriterCharacterCardProps {
  character: WriterCharacter;
  isFocused?: boolean;
  onCardFocus?: () => void;
  onCardBlur?: () => void;
  onDelete: () => void;
  onReview: () => void;
  onCompare: () => void;
  onCategoryChange: (category: CharacterCategory | null) => void;
  onGoalsChange: (goals: string | null) => void;
  onArcNotesChange: (arcNotes: string | null) => void;
  onTraitsChange: (traits: string[]) => void;
  onBooksChange: (books: string[]) => void;
  onNameChange: (name: string) => void;
  onRelationshipsChange: (relationships: { target: string; nature: string }[]) => void;
  onPhotoChange: (photoUrl: string) => void;
  onAliasesChange: (aliases: string | null) => void;
}

function Avatar({
  character,
  onPhotoChange,
  onCropModalChange,
}: {
  character: WriterCharacter;
  onPhotoChange: (photoUrl: string) => void;
  onCropModalChange?: (open: boolean) => void;
}) {
  const { showToast } = useAppStore();
  const inputRef = useRef<HTMLInputElement>(null);
  const [cropFile, setCropFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  const initials = character.name
    .trim()
    .split(" ")
    .map((w) => w[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase() || "?";

  // Tracks whether the OS file picker is currently open so we can suppress card blur
  const filePickingRef = useRef(false);

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    filePickingRef.current = false; // picker closed with a file — window focus handler won't unlock
    const file = e.target.files?.[0];
    if (file) {
      setCropFile(file);
      // onCropModalChange already true from handleAvatarClick; keep it locked for crop modal
    } else {
      onCropModalChange?.(false);
    }
    e.target.value = "";
  };

  const handleAvatarClick = () => {
    if (uploading) return;
    // Lock BEFORE the OS dialog opens so window-blur doesn't trigger onCardBlur
    filePickingRef.current = true;
    onCropModalChange?.(true);

    // If the user cancels the file picker, window.focus fires but handleFile won't.
    // Use that to release the lock. Delay 200ms so handleFile (change event) runs first
    // if a file was selected — it will clear filePickingRef, preventing the unlock.
    const onWindowFocus = () => {
      window.removeEventListener("focus", onWindowFocus);
      setTimeout(() => {
        if (filePickingRef.current) {
          filePickingRef.current = false;
          onCropModalChange?.(false);
        }
      }, 200);
    };
    window.addEventListener("focus", onWindowFocus);

    inputRef.current?.click();
  };

  const handleCropConfirm = useCallback(async (blob: Blob) => {
    setCropFile(null);
    onCropModalChange?.(false);
    setUploading(true);
    try {
      const file = new File([blob], "avatar.jpg", { type: "image/jpeg" });
      const url = await uploadWriterCharacterPhoto(character.id, file);
      onPhotoChange(url);
    } catch {
      showToast("Failed to upload photo.");
    } finally {
      setUploading(false);
    }
  }, [character.id, onPhotoChange, showToast]);

  return (
    <>
      <div
        className="group relative h-10 w-10 flex-shrink-0 rounded-full overflow-hidden cursor-pointer"
        onMouseDown={(e) => e.preventDefault()}
        onClick={handleAvatarClick}
      >
        {character.photo_url ? (
          <img src={character.photo_url} alt={character.name} className="h-full w-full object-cover" />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-accent/20 ring-1 ring-accent/30">
            <span className="text-xs font-semibold text-accent">{initials}</span>
          </div>
        )}
        <div className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity">
          <Camera className="h-3.5 w-3.5 text-white" />
        </div>
        <input ref={inputRef} type="file" accept="image/*" className="hidden" onChange={handleFile} />
      </div>
      {cropFile && (
        <PhotoCropModal
          file={cropFile}
          onConfirm={handleCropConfirm}
          onCancel={() => { setCropFile(null); onCropModalChange?.(false); }}
        />
      )}
    </>
  );
}

export default function WriterCharacterCard({
  character,
  isFocused,
  onCardFocus,
  onCardBlur,
  onDelete,
  onReview,
  onCompare,
  onCategoryChange,
  onGoalsChange,
  onArcNotesChange,
  onTraitsChange,
  onBooksChange,
  onNameChange,
  onRelationshipsChange,
  onPhotoChange,
  onAliasesChange,
}: WriterCharacterCardProps) {
  const { books: allBooks } = useAppStore();
  const cat = character.category ?? null;
  const [cropModalOpen, setCropModalOpen] = useState(false);
  const firstName = character.name.trim().split(/\s+/)[0];

  const [name, setName] = useState(character.name);
  useEffect(() => { setName(character.name); }, [character.name]);

  const [aliases, setAliases] = useState(character.aliases ?? "");
  useEffect(() => { setAliases(character.aliases ?? ""); }, [character.aliases]);

  const [goals, setGoals] = useState(character.goals ?? "");
  const [arcNotes, setArcNotes] = useState(character.arc_notes ?? "");

  useEffect(() => { setGoals(character.goals ?? ""); }, [character.goals]);
  useEffect(() => { setArcNotes(character.arc_notes ?? ""); }, [character.arc_notes]);

  // Traits
  const [localTraits, setLocalTraits] = useState(character.traits);
  const [addingTrait, setAddingTrait] = useState(false);
  const [newTraitValue, setNewTraitValue] = useState("");
  const newTraitInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setLocalTraits(character.traits); }, [character.traits]);

  const [localRelationships, setLocalRelationships] = useState(character.relationships);
  const [addingRel, setAddingRel] = useState(false);
  const [newRelTarget, setNewRelTarget] = useState("");
  const [newRelNature, setNewRelNature] = useState("");
  const [relDropdownOpen, setRelDropdownOpen] = useState(false);
  const [relDropdownPos, setRelDropdownPos] = useState({ top: 0, left: 0, width: 0 });
  const relTargetRef = useRef<HTMLInputElement>(null);
  const relNatureRef = useRef<HTMLInputElement>(null);
  const relNatureEnterRef = useRef(false);
  const { writerCharacters } = usePlanStore();

  useEffect(() => { setLocalRelationships(character.relationships); }, [character.relationships]);

  useEffect(() => {
    if (addingRel) relTargetRef.current?.focus();
  }, [addingRel]);

  // Close dropdown on outside click
  useEffect(() => {
    if (!relDropdownOpen) return;
    const handler = (e: MouseEvent) => {
      if (!relTargetRef.current?.contains(e.target as Node)) setRelDropdownOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [relDropdownOpen]);

  const openRelDropdown = () => {
    const rect = relTargetRef.current?.getBoundingClientRect();
    if (rect) setRelDropdownPos({ top: rect.bottom + 4, left: rect.left, width: rect.width });
    setRelDropdownOpen(true);
  };

  const selectRelTarget = (name: string) => {
    setNewRelTarget(name);
    setRelDropdownOpen(false);
    relNatureRef.current?.focus();
  };

  const filteredChars = writerCharacters.filter(
    (c) => c.id !== character.id && c.name && c.name.toLowerCase().includes(newRelTarget.toLowerCase())
  );

  const confirmNewRel = (keepOpen = false) => {
    const target = newRelTarget.trim();
    if (target) {
      const updated = [...localRelationships, { target, nature: newRelNature.trim() }];
      setLocalRelationships(updated);
      onRelationshipsChange(updated);
    }
    setNewRelTarget("");
    setNewRelNature("");
    if (keepOpen) {
      requestAnimationFrame(() => relTargetRef.current?.focus());
    } else {
      setAddingRel(false);
    }
  };

  const removeRelationship = (i: number) => {
    const updated = localRelationships.filter((_, idx) => idx !== i);
    setLocalRelationships(updated);
    onRelationshipsChange(updated);
  };

  useEffect(() => {
    if (addingTrait) newTraitInputRef.current?.focus();
  }, [addingTrait]);

  const confirmNewTrait = (keepOpen = false) => {
    const t = newTraitValue.trim();
    if (t && !localTraits.includes(t)) {
      const updated = [...localTraits, t];
      setLocalTraits(updated);
      onTraitsChange(updated);
    }
    setNewTraitValue("");
    if (keepOpen) {
      newTraitInputRef.current?.focus();
    } else {
      setAddingTrait(false);
    }
  };

  const removeTrait = (trait: string) => {
    const updated = localTraits.filter((t) => t !== trait);
    setLocalTraits(updated);
    onTraitsChange(updated);
  };

  return (
    <div
      data-character-id={character.id}
      className={clsx(
        "group relative rounded-lg flex flex-col overflow-hidden border bg-surface-card p-4 transition-colors",
        isFocused
          ? "border-accent/60 ring-2 ring-accent/25"
          : "border-surface-border hover:border-surface-border/80"
      )}
      onFocus={onCardFocus}
      onBlur={(e) => {
        // Only fire blur when focus leaves the card entirely and no portal modal is open
        if (!cropModalOpen && !e.currentTarget.contains(e.relatedTarget as Node | null)) {
          onCardBlur?.();
        }
      }}
    >
      {/* Top row — avatar + name/role/category + actions */}
      <div className="flex items-start gap-3">
        <Avatar character={character} onPhotoChange={onPhotoChange} onCropModalChange={setCropModalOpen} />
        <div className="flex-1 min-w-0">
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            onBlur={() => { if (name.trim()) onNameChange(name.trim()); else setName(character.name); }}
            placeholder="What is this character's name?"
            className="w-full bg-transparent text-xs font-semibold text-ink-primary placeholder-ink-muted/60 outline-none focus:border-b focus:border-surface-border truncate"
          />
          <input
            type="text"
            value={aliases}
            onChange={(e) => setAliases(e.target.value)}
            onBlur={() => onAliasesChange(aliases.trim() || null)}
            placeholder="Known aliases"
            className="w-full bg-transparent text-[11px] text-ink-muted placeholder-ink-muted/60 outline-none focus:border-b focus:border-surface-border truncate"
          />
          {character.role && (
            <p className="text-[11px] text-ink-muted truncate">{character.role}</p>
          )}
        </div>
        {/* Actions */}
        <div className="flex items-center opacity-0 group-hover:opacity-100 transition-opacity" style={{ gap: "8px" }}>
          <div className="relative group/tip">
            <button
              onClick={onCompare}
              className="rounded p-1 text-ink-muted hover:text-ink-secondary hover:bg-surface-hover transition-colors"
            >
              <GitCompare className="h-3 w-3" />
            </button>
            <div className="pointer-events-none absolute top-full left-1/2 -translate-x-1/2 mt-1.5 z-50 whitespace-nowrap rounded border border-surface-border bg-surface-card px-2 py-1 text-[10px] text-ink-secondary shadow-lg opacity-0 group-hover/tip:opacity-100 transition-opacity duration-150">
              Compare
            </div>
          </div>
          <div className="relative group/tip">
            <button
              onClick={onReview}
              className="rounded p-1 text-accent/60 hover:text-accent hover:bg-accent/10 transition-colors"
            >
              <MessageSquare className="h-3 w-3" />
            </button>
            <div className="pointer-events-none absolute top-full left-1/2 -translate-x-1/2 mt-1.5 z-50 whitespace-nowrap rounded border border-surface-border bg-surface-card px-2 py-1 text-[10px] text-ink-secondary shadow-lg opacity-0 group-hover/tip:opacity-100 transition-opacity duration-150">
              Discuss
            </div>
          </div>
          <div className="relative group/tip">
            <button
              onClick={onDelete}
              className="rounded p-1 text-ink-muted hover:text-red-400 hover:bg-red-400/10 transition-colors"
            >
              <X className="h-3 w-3" />
            </button>
            <div className="pointer-events-none absolute top-full left-1/2 -translate-x-1/2 mt-1.5 z-50 whitespace-nowrap rounded border border-surface-border bg-surface-card px-2 py-1 text-[10px] text-ink-secondary shadow-lg opacity-0 group-hover/tip:opacity-100 transition-opacity duration-150">
              Delete
            </div>
          </div>
        </div>
      </div>

      {/* Category pills */}
      <div className="mt-2 flex items-center gap-1">
        {CATEGORIES.map((c) => (
          <button
            key={c.value}
            onClick={() => onCategoryChange(cat === c.value ? null : c.value)}
            className={clsx(
              "rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors",
              cat === c.value
                ? categoryStyle[c.value]
                : "border-surface-border text-ink-muted/50 hover:text-ink-muted hover:border-surface-border/80"
            )}
          >
            {c.label}
          </button>
        ))}
      </div>

      {/* Goals */}
      <div className="mt-3">
        <textarea
          value={goals}
          onChange={(e) => setGoals(e.target.value)}
          onBlur={() => onGoalsChange(goals.trim() || null)}
          placeholder={`What are ${firstName}'s goals?`}
          rows={2}
          className="w-full resize-none rounded border border-surface-border bg-surface px-2 py-1.5 text-[11px] text-ink-primary placeholder-ink-muted/60 leading-relaxed focus:border-accent/50 focus:outline-none transition-colors"
        />
      </div>

      {/* Arc Notes */}
      <div className="mt-1">
        <textarea
          value={arcNotes}
          onChange={(e) => setArcNotes(e.target.value)}
          onBlur={() => onArcNotesChange(arcNotes.trim() || null)}
          placeholder={`How will ${firstName} develop across this book?`}
          rows={2}
          className="w-full resize-none rounded border border-surface-border bg-surface px-2 py-1.5 text-[11px] text-ink-primary placeholder-ink-muted/60 leading-relaxed focus:border-accent/50 focus:outline-none transition-colors"
        />
      </div>

      {/* Traits */}
      <div className="mt-1">
        <div className="h-[52px] overflow-y-auto flex flex-wrap gap-1.5 content-start pb-0.5">
          {localTraits.map((t) => (
            <span
              key={t}
              title={t}
              className="flex items-center gap-1 w-24 flex-shrink-0 rounded-full bg-surface border border-surface-border px-2 py-0.5"
            >
              <span className="flex-1 min-w-0 truncate text-[10px] text-ink-muted">{t}</span>
              <button
                onClick={() => removeTrait(t)}
                className="flex-shrink-0 text-ink-muted/40 hover:text-red-400 transition-colors"
              >
                <X className="h-2.5 w-2.5" />
              </button>
            </span>
          ))}
          {addingTrait ? (
            <span className="flex items-center w-24 flex-shrink-0 rounded-full bg-surface border border-accent/40 px-2 py-0.5">
              <input
                ref={newTraitInputRef}
                value={newTraitValue}
                onChange={(e) => setNewTraitValue(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") { e.preventDefault(); confirmNewTrait(true); }
                  if (e.key === "Escape") { setNewTraitValue(""); setAddingTrait(false); }
                }}
                onBlur={() => confirmNewTrait(false)}
                className="w-full bg-transparent text-[10px] text-ink-primary outline-none placeholder-ink-muted/40"
                placeholder="trait…"
              />
            </span>
          ) : (
            <button
              onClick={() => setAddingTrait(true)}
              className="flex flex-shrink-0 items-center gap-0.5 rounded-full border border-dashed border-surface-border px-2 py-0.5 text-[10px] text-ink-muted hover:border-accent/50 hover:text-accent transition-colors"
            >
              <Plus className="h-2.5 w-2.5" />
              Add Trait
            </button>
          )}
        </div>
      </div>

      {/* Relationships */}
      <div className="mt-3 pt-3 border-t border-surface-border">
        <div className="flex items-center justify-between mb-1.5">
          <span className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted">
            Relationships {localRelationships.length > 0 && `(${localRelationships.length})`}
          </span>
          <button
            onClick={() => setAddingRel(true)}
            className="flex items-center gap-0.5 text-[10px] text-ink-muted/60 hover:text-accent transition-colors"
          >
            <Plus className="h-2.5 w-2.5" />
            Add Relationship
          </button>
        </div>

        <div className="divide-y divide-surface-border rounded-lg border border-surface-border overflow-y-auto h-[112px]">
        {localRelationships.length === 0 && !addingRel ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-[10px] text-ink-muted/50 italic">No relationships to display</p>
          </div>
        ) : (
          <>
            {localRelationships.map((r, i) => {
              const matched = writerCharacters.find((c) => c.name === r.target);
              const colors = nameColor(r.target);
              return (
                <div key={i} className="flex items-center gap-2 px-2 py-1.5 group/rel">
                  {matched?.photo_url ? (
                    <img
                      src={matched.photo_url}
                      alt={r.target}
                      className="h-6 w-6 rounded-full object-cover flex-shrink-0 ring-1 ring-surface-border"
                    />
                  ) : (
                    <div className={clsx("h-6 w-6 rounded-full flex items-center justify-center flex-shrink-0 ring-1 ring-surface-border", colors.bg)}>
                      <span className={clsx("text-[9px] font-semibold", colors.text)}>{relInitials(r.target)}</span>
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-[11px] font-medium text-ink-primary truncate">{r.target}</p>
                    {r.nature && <p className="text-[10px] italic text-ink-muted truncate">{r.nature}</p>}
                  </div>
                  <button
                    onClick={() => removeRelationship(i)}
                    className="flex-shrink-0 opacity-0 group-hover/rel:opacity-100 text-ink-muted/40 hover:text-red-400 transition-all"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </div>
              );
            })}
            {addingRel && (
              <div className="flex items-center gap-2 px-2 py-1.5">
                <div className="relative w-24 flex-shrink-0">
                  <input
                    ref={relTargetRef}
                    value={newRelTarget}
                    onChange={(e) => { setNewRelTarget(e.target.value); openRelDropdown(); }}
                    onFocus={openRelDropdown}
                    onKeyDown={(e) => {
                      if (e.key === "Escape") { setRelDropdownOpen(false); setNewRelTarget(""); setNewRelNature(""); setAddingRel(false); }
                      if (e.key === "Enter" || e.key === "Tab") {
                        e.preventDefault();
                        if (filteredChars.length > 0) setNewRelTarget(filteredChars[0].name);
                        setRelDropdownOpen(false);
                        relNatureRef.current?.focus();
                      }
                    }}
                    placeholder="Search…"
                    autoComplete="off"
                    className="w-full rounded border border-surface-border bg-surface px-1.5 py-0.5 text-[10px] text-ink-primary placeholder-ink-muted/50 outline-none focus:border-accent/50"
                  />
                  {relDropdownOpen && filteredChars.length > 0 && createPortal(
                    <div
                      style={{ top: relDropdownPos.top, left: relDropdownPos.left, width: Math.max(relDropdownPos.width, 160) }}
                      className="fixed z-50 rounded-md border border-surface-border bg-surface-card shadow-lg overflow-y-auto max-h-[112px]"
                    >
                      {filteredChars.map((c) => (
                        <button
                          key={c.id}
                          onMouseDown={(e) => { e.preventDefault(); selectRelTarget(c.name); }}
                          className="w-full px-2.5 py-1.5 text-left text-[11px] text-ink-secondary hover:bg-surface-hover hover:text-ink-primary transition-colors"
                        >
                          {c.name}
                        </button>
                      ))}
                    </div>,
                    document.body
                  )}
                </div>
                <input
                  ref={relNatureRef}
                  value={newRelNature}
                  onChange={(e) => setNewRelNature(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); relNatureEnterRef.current = true; confirmNewRel(true); } if (e.key === "Escape") { setNewRelTarget(""); setNewRelNature(""); setAddingRel(false); } }}
                  onBlur={() => { if (relNatureEnterRef.current) { relNatureEnterRef.current = false; return; } confirmNewRel(false); }}
                  placeholder="Description"
                  className="flex-1 min-w-0 rounded border border-surface-border bg-surface px-1.5 py-0.5 text-[10px] text-ink-primary placeholder-ink-muted/50 outline-none focus:border-accent/50"
                />
              </div>
            )}
          </>
        )}
        </div>
      </div>

      {/* Book toggles */}
      {allBooks.length > 0 && (
        <div className="mt-3 pt-3 border-t border-surface-border flex flex-wrap gap-2">
          {allBooks.map((book) => {
            const active = character.books.includes(book.name);
            return (
              <button
                key={book.id}
                title={book.name}
                onClick={() => {
                  const updated = active
                    ? character.books.filter((b) => b !== book.name)
                    : [...character.books, book.name];
                  onBooksChange(updated);
                }}
                className={clsx(
                  "truncate rounded px-2 py-1 text-[10px] font-medium transition-colors border",
                  active
                    ? "bg-accent/20 text-accent border-accent/40"
                    : "bg-surface text-ink-muted border-surface-border hover:text-ink-secondary hover:border-surface-border/80"
                )}
              >
                {book.name}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
