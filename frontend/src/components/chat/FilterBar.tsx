import { useEffect, useRef, useState } from "react";
import { ChevronDown, Check } from "lucide-react";
import { clsx } from "clsx";
import { useAppStore } from "../../store/useAppStore";

// ─── Generic dropdown ────────────────────────────────────────────────────────

interface DropdownProps {
  label: string;
  open: boolean;
  onToggle: () => void;
  onClose: () => void;
  active?: boolean;
  children: React.ReactNode;
}

function Dropdown({ label, open, onToggle, onClose, active, children }: DropdownProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handler(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        onClose();
      }
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open, onClose]);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={onToggle}
        className={clsx(
          "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-colors",
          active
            ? "border-accent bg-accent/10 text-accent"
            : "border-surface-border bg-surface text-ink-secondary hover:border-accent/50 hover:text-ink-primary"
        )}
      >
        <span>{label}</span>
        <ChevronDown
          className={clsx("h-3 w-3 transition-transform", open && "rotate-180")}
        />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-50 mt-1 min-w-[180px] rounded-md border border-surface-border bg-surface shadow-lg">
          {children}
        </div>
      )}
    </div>
  );
}

// ─── FilterBar ───────────────────────────────────────────────────────────────

export default function FilterBar() {
  const {
    books,
    selectedBooks,
    setBookFilter,
    clearBookFilter,
    selectedPovs,
    setPovFilter,
    clearPovFilter,
    saveChatAndClear,
    setLiveChatSessionId,
    closeExploreViewer,
  } = useAppStore();

  const clearChat = () => { saveChatAndClear(); setLiveChatSessionId(null); closeExploreViewer(); };

  const [openDropdown, setOpenDropdown] = useState<"povs" | "books" | null>(null);

  const toggle = (name: "povs" | "books") =>
    setOpenDropdown((prev) => (prev === name ? null : name));
  const close = () => setOpenDropdown(null);

  const allPovsSelected = selectedPovs.size === 0;
  const allBooksSelected = selectedBooks.size === 0;

  // Aggregate POVs from selected books only (all books if no filter active)
  const activeBooks = allBooksSelected ? books : books.filter((b) => selectedBooks.has(b.id));
  const povCounts = new Map<string, number>();
  for (const book of activeBooks) {
    for (const ch of book.chapters) {
      if (ch.pov) {
        povCounts.set(ch.pov, (povCounts.get(ch.pov) ?? 0) + 1);
      }
    }
  }
  const allPovs = [...povCounts.entries()]
    .sort((a, b) => b[1] - a[1])
    .map(([pov]) => pov);

  // Drop selected POVs that no longer exist in the available set when book filter changes
  useEffect(() => {
    if (selectedPovs.size === 0) return;
    const available = new Set(allPovs);
    const still = [...selectedPovs].filter((p) => available.has(p));
    if (still.length !== selectedPovs.size) {
      if (still.length === 0) clearPovFilter();
      else setPovFilter(still);
    }
  }, [selectedBooks]); // eslint-disable-line react-hooks/exhaustive-deps

  const handlePovToggle = (pov: string) => {
    clearChat();
    if (allPovsSelected) {
      // Deselecting one from "all selected" → select all except this one
      setPovFilter(allPovs.filter((p) => p !== pov));
    } else {
      const next = new Set(selectedPovs);
      if (next.has(pov)) next.delete(pov);
      else next.add(pov);
      // If all are now checked, reset to empty (= all selected)
      if (next.size === allPovs.length || next.size === 0) clearPovFilter();
      else setPovFilter([...next]);
    }
  };

  const handleBookToggle = (id: string) => {
    clearChat();
    if (allBooksSelected) {
      setBookFilter(allBooks.filter((b) => b.id !== id).map((b) => b.id));
    } else {
      const next = new Set(selectedBooks);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      if (next.size === allBooks.length || next.size === 0) clearBookFilter();
      else setBookFilter([...next]);
    }
  };

  // Books in series order (as returned by the API)
  const allBooks = books;

  const povLabel =
    selectedPovs.size === 0
      ? "All POVs"
      : selectedPovs.size === 1
      ? [...selectedPovs][0]
      : `${selectedPovs.size} POVs`;

  const bookLabel =
    selectedBooks.size === 0
      ? "All Books"
      : selectedBooks.size === 1
      ? allBooks.find((b) => selectedBooks.has(b.id))?.name ?? "1 Book"
      : `${selectedBooks.size} Books`;

  return (
    <div className="flex items-center gap-2 px-6">

      {/* POVs */}
      <Dropdown
        label={povLabel}
        open={openDropdown === "povs"}
        onToggle={() => toggle("povs")}
        onClose={close}
        active={selectedPovs.size > 0}
      >
        <div className="max-h-64 overflow-y-auto py-1">
          {allPovs.length === 0 ? (
            <p className="px-3 py-2 text-xs text-ink-muted">No POVs found</p>
          ) : (
            allPovs.map((pov) => {
              const checked = allPovsSelected || selectedPovs.has(pov);
              return (
                <button
                  key={pov}
                  onClick={() => handlePovToggle(pov)}
                  className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-surface-hover"
                >
                  <span
                    className={clsx(
                      "flex h-3.5 w-3.5 flex-shrink-0 items-center justify-center rounded border",
                      checked ? "border-accent bg-accent" : "border-surface-border"
                    )}
                  >
                    {checked && <Check className="h-2.5 w-2.5 text-white" />}
                  </span>
                  <span className={checked ? "text-ink-primary" : "text-ink-secondary"}>
                    {pov}
                  </span>
                  <span className="ml-auto text-[10px] text-ink-muted">
                    {povCounts.get(pov)}
                  </span>
                </button>
              );
            })
          )}
        </div>
        {!allPovsSelected && (
          <div className="border-t border-surface-border px-3 py-1.5">
            <button
              onClick={() => { clearChat(); clearPovFilter(); }}
              className="text-[10px] text-ink-muted hover:text-accent"
            >
              Select all
            </button>
          </div>
        )}
      </Dropdown>

      {/* Books */}
      <Dropdown
        label={bookLabel}
        open={openDropdown === "books"}
        onToggle={() => toggle("books")}
        onClose={close}
        active={selectedBooks.size > 0}
      >
        <div className="max-h-64 overflow-y-auto py-1">
          {allBooks.map((book) => {
            const checked = allBooksSelected || selectedBooks.has(book.id);
            return (
              <button
                key={book.id}
                onClick={() => handleBookToggle(book.id)}
                className="flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-surface-hover"
              >
                <span
                  className={clsx(
                    "flex h-3.5 w-3.5 flex-shrink-0 items-center justify-center rounded border",
                    checked ? "border-accent bg-accent" : "border-surface-border"
                  )}
                >
                  {checked && <Check className="h-2.5 w-2.5 text-white" />}
                </span>
                <span className={checked ? "text-ink-primary" : "text-ink-secondary"}>
                  {book.name}
                </span>
              </button>
            );
          })}
        </div>
        {!allBooksSelected && (
          <div className="border-t border-surface-border px-3 py-1.5">
            <button
              onClick={() => { clearChat(); clearBookFilter(); }}
              className="text-[10px] text-ink-muted hover:text-accent"
            >
              Select all
            </button>
          </div>
        )}
      </Dropdown>

    </div>
  );
}
