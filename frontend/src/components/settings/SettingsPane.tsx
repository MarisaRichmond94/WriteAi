import { useRef, useState, useCallback, useEffect } from "react";
import { createPortal } from "react-dom";
import { clsx } from "clsx";
import { Camera, ExternalLink, Eye, EyeOff, FolderOpen, GripVertical, Info, Trash2, ImagePlus } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";
import { fetchSettings, saveSettings, pickFolder, uploadWriterPhoto, deleteWriterPhoto, uploadBookCover, deleteBookCover, bookSlug } from "../../api/settings";
import { createNotification } from "../../api/notifications";
import type { AppSettings } from "../../types";

const VALID_MODELS = [
  "claude-sonnet-4-6",
  "claude-opus-4-6",
  "claude-haiku-4-5-20251001",
];

// ── Field components ──────────────────────────────────────────────────────────

function Field({ label, description, infoLink, infoTooltip, children }: { label: string; description?: string; infoLink?: string; infoTooltip?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-1">
        <label className="text-[11px] font-bold uppercase tracking-wider text-ink-muted">
          {label}
        </label>
        {infoLink && (
          <a href={infoLink} target="_blank" rel="noopener noreferrer" className="text-ink-muted hover:text-ink-secondary transition-colors">
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      {description && (
        <div className="flex items-center gap-2 -mt-0.5 mb-0.5">
          <p className="text-[11px] text-ink-muted">{description}</p>
          {infoTooltip && (
            <div className="group relative flex-shrink-0">
              <Info className="h-3 w-3 text-ink-muted hover:text-ink-secondary transition-colors cursor-default" />
              <div className="pointer-events-none absolute left-0 top-5 z-50 w-72 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-[11px] leading-relaxed text-ink-muted shadow-lg opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                {infoTooltip}
              </div>
            </div>
          )}
        </div>
      )}
      {children}
    </div>
  );
}

function TextInput({
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={placeholder}
      className="rounded border border-surface-border bg-surface px-3 py-1.5 text-sm text-ink-primary placeholder-ink-muted focus:outline-none focus:ring-1 focus:ring-accent"
    />
  );
}

function NumberInput({
  value,
  onChange,
  min,
}: {
  value: number;
  onChange: (v: number) => void;
  min?: number;
}) {
  return (
    <input
      type="number"
      value={value}
      min={min}
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-28 rounded border border-surface-border bg-surface px-3 py-1.5 text-sm text-ink-primary focus:outline-none focus:ring-1 focus:ring-accent"
    />
  );
}

function PasswordInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div className="relative flex items-center">
      <input
        type={show ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded border border-surface-border bg-surface px-3 py-1.5 pr-9 text-sm text-ink-primary placeholder-ink-muted focus:outline-none focus:ring-1 focus:ring-accent"
      />
      <button
        type="button"
        onClick={() => setShow((s) => !s)}
        className="absolute right-2.5 text-ink-muted hover:text-ink-secondary transition-colors"
      >
        {show ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

function ModelSelect({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded border border-surface-border bg-surface px-3 py-1.5 pr-10 text-sm text-ink-primary focus:outline-none focus:ring-1 focus:ring-accent"
    >
      {VALID_MODELS.map((m) => (
        <option key={m} value={m}>
          {m}
        </option>
      ))}
    </select>
  );
}

function FolderInput({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  const [picking, setPicking] = useState(false);

  const handlePick = async () => {
    setPicking(true);
    try {
      const path = await pickFolder(value || undefined);
      if (path) onChange(path);
    } catch {
      // user cancelled or error — leave field unchanged
    } finally {
      setPicking(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="flex-1 rounded border border-surface-border bg-surface px-3 py-1.5 text-sm text-ink-primary placeholder-ink-muted focus:outline-none focus:ring-1 focus:ring-accent"
      />
      <button
        type="button"
        onClick={handlePick}
        disabled={picking}
        title="Browse for folder"
        className="flex-shrink-0 rounded px-1 py-1.5 text-ink-muted transition-colors hover:bg-surface-hover hover:text-accent disabled:opacity-50"
      >
        <FolderOpen className="h-4 w-4" />
      </button>
    </div>
  );
}

// ── Drag-and-drop book order ──────────────────────────────────────────────────

function BookOrderList({
  books,
  onChange,
}: {
  books: string[];
  onChange: (order: string[]) => void;
}) {
  const dragIdx = useRef<number | null>(null);

  const handleDragStart = (i: number) => {
    dragIdx.current = i;
  };

  const handleDrop = (i: number) => {
    if (dragIdx.current === null || dragIdx.current === i) return;
    const next = [...books];
    const [moved] = next.splice(dragIdx.current, 1);
    next.splice(i, 0, moved);
    dragIdx.current = null;
    onChange(next);
  };

  return (
    <div className="flex flex-col gap-2">
      {books.map((book, i) => (
        <div
          key={book}
          draggable
          onDragStart={() => handleDragStart(i)}
          onDragOver={(e) => e.preventDefault()}
          onDrop={() => handleDrop(i)}
          className="flex cursor-grab items-center gap-2 rounded border border-surface-border bg-surface px-3 py-2 text-sm text-ink-primary active:cursor-grabbing"
        >
          <GripVertical className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
          <span className="truncate">{book}</span>
        </div>
      ))}
      {books.length === 0 && (
        <p className="text-[11px] text-ink-muted">
          No books discovered in the configured Books folder.
        </p>
      )}
    </div>
  );
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
          <button onClick={handleConfirm} className="rounded-md bg-accent px-4 py-2 text-xs font-medium text-white transition-colors hover:bg-accent/90">Save</button>
        </div>
      </div>
    </div>,
    document.body
  );
}

// ── Writer profile avatar ─────────────────────────────────────────────────────

function WriterAvatar({
  name,
  photoUrl,
  onUploaded,
  onDeleted,
}: {
  name: string;
  photoUrl: string | null;
  onUploaded: (url: string) => void;
  onDeleted: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [cropFile, setCropFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);

  const initials = name.trim()
    ? name.trim().split(" ").map((w) => w[0]).slice(0, 2).join("").toUpperCase()
    : "W";

  const handleFile = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    setCropFile(file);
  };

  const handleCropConfirm = useCallback(async (blob: Blob) => {
    setCropFile(null);
    const file = new File([blob], "photo.jpg", { type: "image/jpeg" });
    setUploading(true);
    try {
      const url = await uploadWriterPhoto(file);
      onUploaded(url);
    } finally {
      setUploading(false);
    }
  }, [onUploaded]);

  const handleDelete = async () => {
    await deleteWriterPhoto();
    onDeleted();
  };

  return (
    <div className="flex items-center gap-4">
      {/* Avatar */}
      <div className="group relative h-16 w-16 flex-shrink-0 rounded-full overflow-hidden">
        {photoUrl ? (
          <img
            src={`${photoUrl}?t=${Date.now()}`}
            alt={name}
            className="h-full w-full object-cover"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-accent/20 text-lg font-semibold text-accent">
            {initials}
          </div>
        )}
        <button
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity disabled:cursor-wait"
          title="Upload photo"
        >
          <Camera className="h-5 w-5 text-white" />
        </button>
          <input ref={inputRef} type="file" accept="image/jpeg,image/png" className="hidden" onChange={handleFile} />
      </div>

      {cropFile && (
        <PhotoCropModal
          file={cropFile}
          onConfirm={handleCropConfirm}
          onCancel={() => setCropFile(null)}
        />
      )}

      {/* Actions */}
      <div className="flex flex-col gap-1.5">
        <button
          onClick={() => inputRef.current?.click()}
          disabled={uploading}
          className="text-left text-[11px] text-ink-secondary hover:text-ink-primary transition-colors disabled:opacity-50"
        >
          {uploading ? "Uploading…" : "Upload photo"}
        </button>
        {photoUrl && (
          <button
            onClick={handleDelete}
            className="flex items-center gap-1 text-left text-[11px] text-red-400 hover:text-red-300 transition-colors"
          >
            <Trash2 className="h-3 w-3" />
            Remove photo
          </button>
        )}
        <p className="text-[10px] text-ink-muted">JPEG or PNG</p>
      </div>
    </div>
  );
}

// ── Section wrapper ───────────────────────────────────────────────────────────

function Section({ title, infoLink, children }: { title: string; infoLink?: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-ink-primary">
          {title}
        </p>
        {infoLink && (
          <a href={infoLink} target="_blank" rel="noopener noreferrer" className="text-ink-muted hover:text-ink-secondary transition-colors">
            <ExternalLink className="h-3 w-3" />
          </a>
        )}
      </div>
      <div className="flex flex-col gap-3">{children}</div>
    </div>
  );
}

// ── Book cover upload ─────────────────────────────────────────────────────────

function BookCoverCard({ book }: { book: string }) {
  const slug = bookSlug(book);
  const [timestamp, setTimestamp] = useState(Date.now());
  const [coverLoaded, setCoverLoaded] = useState(false);
  const [uploading, setUploading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const imgSrc = `/api/settings/book-cover/${slug}?t=${timestamp}`;

  const handleFile = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    e.target.value = "";
    setUploading(true);
    try {
      await uploadBookCover(slug, file);
      setTimestamp(Date.now());
    } finally {
      setUploading(false);
    }
  };

  const handleDelete = async () => {
    await deleteBookCover(slug);
    setCoverLoaded(false);
    setTimestamp(Date.now());
  };

  return (
    <div className="flex items-center gap-4 rounded border border-surface-border bg-surface px-4 py-3">
      {/* Cover preview */}
      <div
        className="group relative h-16 w-12 flex-shrink-0 rounded overflow-hidden border border-surface-border cursor-pointer"
        onClick={() => inputRef.current?.click()}
        title="Upload cover"
      >
        <img
          src={imgSrc}
          alt={book}
          onLoad={() => setCoverLoaded(true)}
          onError={() => setCoverLoaded(false)}
          className={clsx("h-full w-full object-cover", !coverLoaded && "hidden")}
        />
        {!coverLoaded && (
          <div className="flex h-full w-full items-center justify-center bg-surface-card">
            <ImagePlus className="h-4 w-4 text-ink-muted" />
          </div>
        )}
        <div className="absolute inset-0 flex items-center justify-center bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity">
          <Camera className="h-4 w-4 text-white" />
        </div>
      </div>

      <input ref={inputRef} type="file" accept="image/jpeg,image/png" className="hidden" onChange={handleFile} />

      {/* Book name + actions */}
      <div className="flex flex-1 flex-col gap-1 min-w-0">
        <span className="truncate text-sm text-ink-primary">{book}</span>
        <div className="flex items-center gap-3">
          <button
            onClick={() => inputRef.current?.click()}
            disabled={uploading}
            className="text-[11px] text-ink-secondary hover:text-ink-primary transition-colors disabled:opacity-50"
          >
            {uploading ? "Uploading…" : coverLoaded ? "Replace cover" : "Upload cover"}
          </button>
          {coverLoaded && (
            <button
              onClick={handleDelete}
              className="flex items-center gap-1 text-[11px] text-red-400 hover:text-red-300 transition-colors"
            >
              <Trash2 className="h-3 w-3" />
              Remove
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

const TABS = ["General", "Profile", "API Keys", "Sync", "Books", "AI Models"] as const;
type Tab = typeof TABS[number];

// ── Main component ────────────────────────────────────────────────────────────

export default function SettingsPane() {
  const { showToast, setAppSettings } = useAppStore();

  const [activeTab, setActiveTab] = useState<Tab>("General");
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);

  // Form state
  const [siteName, setSiteName] = useState("The Archive");
  const [sourceBooksDir, setSourceBooksDir] = useState("");
  const [booksDir, setBooksDir] = useState("");
  const [dataDir, setDataDir] = useState("");
  const [backupDays, setBackupDays] = useState(30);
  const [syncTime, setSyncTime] = useState("02:00");
  const [autoSyncEnabled, setAutoSyncEnabled] = useState(true);
  const [bookOrder, setBookOrder] = useState<string[]>([]);
  const [discoveredBooks, setDiscoveredBooks] = useState<string[]>([]);
  const [queryModel, setQueryModel] = useState(VALID_MODELS[0]);
  const [extractionModel, setExtractionModel] = useState(VALID_MODELS[2]);
  const [anthropicKey, setAnthropicKey] = useState("");
  const [openaiKey, setOpenaiKey] = useState("");
  const [writerName, setWriterName] = useState("Writer");
  const [writerPhotoUrl, setWriterPhotoUrl] = useState<string | null>(null);
  const [viewerLightMode, setViewerLightMode] = useState(true);

  // Redacted placeholders from server (used to detect unchanged keys)
  const anthropicPreviewRef = useRef("");
  const openaiPreviewRef = useRef("");

  useEffect(() => {
    fetchSettings()
      .then((s) => {
        setSiteName(s.site_name);
        setSourceBooksDir(s.source_books_dir);
        setBooksDir(s.books_dir);
        setDataDir(s.data_dir);
        setBackupDays(s.backup_retention_days);
        setSyncTime(s.sync_time);
        setAutoSyncEnabled(s.auto_sync_enabled ?? true);
        // Merge discovered books with configured order
        const configured = s.book_order.length > 0 ? s.book_order : s.discovered_books;
        setBookOrder(configured);
        setDiscoveredBooks(s.discovered_books);
        setQueryModel(s.query_model);
        setExtractionModel(s.extraction_model);
        setAnthropicKey(s.anthropic_api_key_preview);
        setOpenaiKey(s.openai_api_key_preview);
        anthropicPreviewRef.current = s.anthropic_api_key_preview;
        openaiPreviewRef.current = s.openai_api_key_preview;
        setWriterName(s.writer_name ?? "Writer");
        setWriterPhotoUrl(s.writer_photo_url ?? null);
        setViewerLightMode(s.viewer_light_mode ?? true);
        setLoaded(true);
      })
      .catch(() => showToast("Failed to load settings."));
  }, []);

  const handleReset = async () => {
    setResetting(true);
    try {
      const s = await fetchSettings();
      setSiteName(s.site_name);
      setSourceBooksDir(s.source_books_dir);
      setBooksDir(s.books_dir);
      setDataDir(s.data_dir);
      setBackupDays(s.backup_retention_days);
      setSyncTime(s.sync_time);
      setAutoSyncEnabled(s.auto_sync_enabled ?? true);
      setBookOrder(s.book_order.length > 0 ? s.book_order : s.discovered_books);
      setDiscoveredBooks(s.discovered_books);
      setQueryModel(s.query_model);
      setExtractionModel(s.extraction_model);
      setAnthropicKey(s.anthropic_api_key_preview);
      setOpenaiKey(s.openai_api_key_preview);
      anthropicPreviewRef.current = s.anthropic_api_key_preview;
      openaiPreviewRef.current = s.openai_api_key_preview;
      setWriterName(s.writer_name ?? "Writer");
      setWriterPhotoUrl(s.writer_photo_url ?? null);
      setViewerLightMode(s.viewer_light_mode ?? true);
    } catch {
      showToast("Failed to reload settings.");
    } finally {
      setResetting(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    try {
      const updates: Parameters<typeof saveSettings>[0] = {
        site_name: siteName,
        writer_name: writerName,
        source_books_dir: sourceBooksDir,
        books_dir: booksDir,
        data_dir: dataDir,
        backup_retention_days: backupDays,
        sync_time: syncTime,
        auto_sync_enabled: autoSyncEnabled,
        book_order: bookOrder,
        query_model: queryModel,
        extraction_model: extractionModel,
        viewer_light_mode: viewerLightMode,
      };
      // Only include API keys if they've been changed from the redacted preview
      if (anthropicKey && anthropicKey !== anthropicPreviewRef.current) {
        updates.anthropic_api_key = anthropicKey;
      }
      if (openaiKey && openaiKey !== openaiPreviewRef.current) {
        updates.openai_api_key = openaiKey;
      }
      await saveSettings(updates);

      // Refresh store
      const refreshed = await fetchSettings();
      setAppSettings(refreshed);
      document.title = refreshed.site_name;
      anthropicPreviewRef.current = refreshed.anthropic_api_key_preview;
      openaiPreviewRef.current = refreshed.openai_api_key_preview;
      setAnthropicKey(refreshed.anthropic_api_key_preview);
      setOpenaiKey(refreshed.openai_api_key_preview);
      setWriterName(refreshed.writer_name ?? "Writer");
      setWriterPhotoUrl(refreshed.writer_photo_url ?? null);

      createNotification({
        type: "sync_complete",
        title: "Settings saved",
        body: "Your changes have been applied.",
      }).catch(() => {/* silent */});
    } catch {
      showToast("Failed to save settings.");
    } finally {
      setSaving(false);
    }
  };

  if (!loaded) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <span className="text-sm text-ink-muted">Loading settings…</span>
      </div>
    );
  }

  // Books not yet in the configured order — append at bottom
  const orderedBooks = [
    ...bookOrder,
    ...discoveredBooks.filter((b) => !bookOrder.includes(b)),
  ];

  return (
    <div className="flex flex-1 flex-col overflow-hidden">
      {/* Header */}
      <div className="flex-shrink-0 px-6 pt-4 pb-0">
        <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">
          Settings
        </p>
        <p className="mt-0.5 text-[11px] text-ink-muted">
          Configure your NovelRAG installation
        </p>

        <div className="mt-3 border-t border-surface-border" />

        {/* Tabs */}
        <div className="flex items-center gap-1 overflow-x-auto pt-[13px] pb-1 pl-px scrollbar-hide">
          {TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={clsx(
                "flex-shrink-0 rounded-full px-3 py-1 text-xs transition-colors",
                activeTab === tab
                  ? "bg-accent/20 text-accent ring-1 ring-accent/40"
                  : "text-ink-secondary hover:bg-surface-hover"
              )}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        <div className="flex flex-col gap-4">

          {activeTab === "Profile" && (
            <Section title="Profile">
              <Field label="Name" description="Your display name, shown throughout the app">
                <TextInput value={writerName} onChange={setWriterName} placeholder="Writer" />
              </Field>
              <Field label="Profile Picture">
                <WriterAvatar
                  name={writerName}
                  photoUrl={writerPhotoUrl}
                  onUploaded={(url) => setWriterPhotoUrl(url)}
                  onDeleted={() => setWriterPhotoUrl(null)}
                />
              </Field>
            </Section>
          )}

          {activeTab === "General" && (
            <Section title="General">
              <Field label="Site Name" description="The title of the website, used throughout the app">
                <TextInput value={siteName} onChange={setSiteName} placeholder="The Archive" />
              </Field>
              <Field label="Source Books Folder" description="The folder where you keep your original book files (.pages, .docx, .pdf). The app watches this folder nightly and handles everything from there">
                <FolderInput value={sourceBooksDir} onChange={setSourceBooksDir} placeholder="~/RagBooks/SourceBooks" />
              </Field>
              <Field label="Books Folder" description="The folder where all of the chapters of your book will be stored. Each book should be a subfolder">
                <FolderInput value={booksDir} onChange={setBooksDir} placeholder="~/RagBooks/Books" />
              </Field>
              <Field label="Data Folder" description="The folder where all extracted insights - knowledge, character data, and backups - will be retained">
                <FolderInput value={dataDir} onChange={setDataDir} placeholder="~/RagBooks/Data" />
              </Field>
              <Field label="Backup Retention" description="How long to keep automatic backups before they're deleted">
                <select
                  value={backupDays}
                  onChange={(e) => setBackupDays(Number(e.target.value))}
                  className="w-full rounded border border-surface-border bg-surface px-2 py-1.5 pr-8 text-sm text-ink-primary focus:outline-none focus:ring-1 focus:ring-accent"
                >
                  {[7, 14, 30, 60, 90].map((d) => (
                    <option key={d} value={d}>{d} days</option>
                  ))}
                  <option value={0}>Forever</option>
                </select>
              </Field>
              <Field label="Document Viewer" description="Default appearance for the chapter viewer when reading source passages">
                <div className="flex items-center gap-3">
                  <button
                    type="button"
                    onClick={() => setViewerLightMode((v) => !v)}
                    className={clsx(
                      "relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface",
                      viewerLightMode ? "bg-accent" : "bg-surface-border"
                    )}
                    role="switch"
                    aria-checked={viewerLightMode}
                  >
                    <span className={clsx("pointer-events-none inline-block h-4 w-4 transform rounded-full bg-white shadow ring-0 transition duration-200", viewerLightMode ? "translate-x-4" : "translate-x-0")} />
                  </button>
                  <span className="text-sm text-ink-secondary">{viewerLightMode ? "Light Mode" : "Dark Mode"}</span>
                </div>
              </Field>
            </Section>
          )}

          {activeTab === "API Keys" && (
            <Section title="API Keys">
              <Field label="Anthropic API Key" description="Required for chat queries and knowledge extraction" infoLink="https://platform.claude.com/docs/en/api/overview#getting-api-keys">
                <PasswordInput
                  value={anthropicKey}
                  onChange={setAnthropicKey}
                  placeholder="sk-ant-…"
                />
              </Field>
              <Field label="OpenAI API Key" description="Required for data processing and retrieval to work" infoLink="https://platform.openai.com/api-keys">
                <PasswordInput
                  value={openaiKey}
                  onChange={setOpenaiKey}
                  placeholder="sk-…"
                />
              </Field>
            </Section>
          )}

          {activeTab === "Sync" && (
            <Section title="Sync Schedule">
              <Field
                label="Automated Nightly Sync"
                description="When enabled, the app will automatically run the extraction pipeline each night at the time below."
              >
                <button
                  type="button"
                  onClick={() => setAutoSyncEnabled((v) => !v)}
                  className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 focus:outline-none ${autoSyncEnabled ? "bg-accent" : "bg-surface-hover"}`}
                  role="switch"
                  aria-checked={autoSyncEnabled}
                >
                  <span
                    className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition duration-200 ${autoSyncEnabled ? "translate-x-5" : "translate-x-0"}`}
                  />
                </button>
              </Field>
              <Field
                label="Nightly Sync Time (UTC)"
                description="The time each night when the app automatically backs up your data and re-runs knowledge extraction (if necessary)"
                infoTooltip="The extraction pipeline only processes content that hasn't been extracted yet. Each chapter is cached after its first run — on subsequent syncs, only new chapters are extracted and only characters without an existing profile are analysed. Nothing is reprocessed unless you trigger a forced re-extraction manually."
              >
                <input
                  type="time"
                  value={syncTime}
                  onChange={(e) => setSyncTime(e.target.value)}
                  disabled={!autoSyncEnabled}
                  className="w-full rounded border border-surface-border bg-surface px-3 py-1.5 text-sm text-ink-primary [color-scheme:dark] focus:outline-none focus:ring-1 focus:ring-accent disabled:opacity-40 disabled:cursor-not-allowed"
                />
              </Field>
            </Section>
          )}

          {activeTab === "Books" && (
            <>
              <Section title="Reading Order">
                <p className="text-[11px] text-ink-muted -mt-2">
                  Drag to set the order books are processed and displayed throughout the app. Books are discovered automatically from your Books Folder and ordered alphabetically by default
                </p>
                <BookOrderList
                  books={orderedBooks}
                  onChange={(order) => setBookOrder(order)}
                />
              </Section>
              <Section title="Book Covers">
                <p className="text-[11px] text-ink-muted -mt-2">
                  Upload cover images for each book. Covers are displayed across the app for visual reference.
                </p>
                <div className="flex flex-col gap-2">
                  {orderedBooks.map((book) => (
                    <BookCoverCard key={book} book={book} />
                  ))}
                  {orderedBooks.length === 0 && (
                    <p className="text-[11px] text-ink-muted">No books discovered yet.</p>
                  )}
                </div>
              </Section>
            </>
          )}

          {activeTab === "AI Models" && (
            <Section title="AI Models" infoLink="https://platform.claude.com/docs/en/about-claude/models/overview">
              <Field label="Query Model" description="The Claude model used to answer your chat questions. More powerful models give richer responses but cost more">
                <ModelSelect value={queryModel} onChange={setQueryModel} />
              </Field>
              <Field label="Extraction Model" description="The Claude model used during knowledge extraction. A faster, cheaper model is usually sufficient for this structured task">
                <ModelSelect value={extractionModel} onChange={setExtractionModel} />
              </Field>
            </Section>
          )}

        </div>
      </div>

      {/* Footer */}
      <div className="flex-shrink-0 border-t border-surface-border bg-surface-card px-6 py-3 flex justify-end">
        <div className="flex gap-2">
          <button
            onClick={handleReset}
            disabled={resetting || saving}
            className="rounded border border-surface-border px-4 py-1.5 text-sm font-medium text-ink-secondary hover:text-ink-primary hover:border-ink-muted disabled:opacity-50 transition-colors"
          >
            {resetting ? "Resetting…" : "Reset"}
          </button>
          <button
            onClick={handleSave}
            disabled={saving || resetting}
            className="rounded bg-accent px-4 py-1.5 text-sm font-medium text-white hover:bg-accent/90 disabled:opacity-50 transition-opacity"
          >
            {saving ? "Saving…" : "Save Settings"}
          </button>
        </div>
      </div>
    </div>
  );
}
