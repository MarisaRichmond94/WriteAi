// Shared layout primitives matching the reference app: per-pane headers,
// bordered dropdown filters, segmented toggles, book tab rows.

import { ReactNode, useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { ChevronDown, Info, LucideIcon } from "lucide-react";
import { bookColor } from "../lib/palette";
import type { Book } from "../types";

export function PaneHeader({
  icon: Icon,
  title,
  info,
  subtitle,
}: {
  icon: LucideIcon;
  title: string;
  info?: string;
  subtitle: string;
}) {
  return (
    <div className="flex-shrink-0 px-6 pb-3 pt-4">
      <div className="flex items-center gap-2">
        <Icon className="h-6 w-6 flex-shrink-0 text-accent" strokeWidth={1.5} />
        <div>
          <div className="flex items-center gap-2">
            <p className="text-xs font-semibold uppercase tracking-widest text-ink-primary">{title}</p>
            {info && (
              <div className="group relative">
                <Info className="h-3.5 w-3.5 cursor-default text-ink-muted transition-colors hover:text-ink-secondary" strokeWidth={1.5} />
                <div className="pointer-events-none absolute left-0 top-5 z-50 w-72 rounded-md border border-surface-border bg-surface-card px-3 py-2 text-[11px] leading-relaxed text-ink-muted opacity-0 shadow-lg transition-opacity duration-150 group-hover:opacity-100">
                  {info}
                </div>
              </div>
            )}
          </div>
          <p className="mt-0.5 text-[11px] text-ink-muted">{subtitle}</p>
        </div>
      </div>
      <div className="mt-3 border-t border-surface-border" />
    </div>
  );
}

export function Dropdown({
  label,
  options,
  value,
  onChange,
  accentClass,
  align = "left",
}: {
  label: string;
  options: { value: string; label: string }[];
  value: string;
  onChange: (v: string) => void;
  accentClass?: string;
  align?: "left" | "right";
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, []);
  const current = options.find((o) => o.value === value);
  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          "flex items-center gap-1.5 rounded border bg-surface px-2.5 py-1 text-[11px] transition-colors hover:border-accent",
          accentClass ?? "border-surface-border text-ink-secondary hover:text-ink-primary",
        )}
      >
        {current?.label ?? label}
        <ChevronDown className="h-3 w-3 flex-shrink-0" strokeWidth={1.5} />
      </button>
      {open && (
        <div
          className={clsx(
            "absolute top-full z-50 mt-1 max-h-72 min-w-[160px] overflow-y-auto rounded-md border border-surface-border bg-surface-card shadow-lg",
            align === "right" ? "right-0" : "left-0",
          )}
        >
          {options.map((o) => (
            <button
              key={o.value}
              onClick={() => {
                onChange(o.value);
                setOpen(false);
              }}
              className={clsx(
                "block w-full px-3 py-1.5 text-left text-[11px] transition-colors hover:bg-surface-hover",
                o.value === value ? "text-accent" : "text-ink-secondary",
              )}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function Segmented({
  options,
  value,
  onChange,
}: {
  options: { value: string; label: ReactNode }[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div className="flex items-center overflow-hidden rounded border border-surface-border">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={clsx(
            "px-2.5 py-1 text-[11px] transition-colors",
            value === o.value
              ? "bg-accent/20 font-medium text-accent"
              : "text-ink-secondary hover:bg-surface-hover hover:text-ink-primary",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export function BookTabs({
  books,
  value,
  onChange,
}: {
  books: Book[];
  value: number;
  onChange: (id: number) => void;
}) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {books.map((b) => (
        <button
          key={b.id}
          onClick={() => onChange(b.id)}
          className={clsx(
            "rounded-full px-3 py-1 text-[11px] font-medium transition-colors",
            value === b.id
              ? "bg-accent text-white"
              : clsx("opacity-70 hover:opacity-100", bookColor(b.id)),
          )}
        >
          {b.name}
        </button>
      ))}
    </div>
  );
}

/** Bottom ghost action bar (Rebuild Index / Re-Extract Character Data). */
export function FooterAction({
  children,
  status,
}: {
  children: ReactNode;
  status?: ReactNode;
}) {
  return (
    <div className="flex-shrink-0 border-t border-surface-border">
      <div className="px-6 py-2.5">{children}</div>
      {status && <div className="px-6 pb-2 text-[10px] text-ink-muted">{status}</div>}
    </div>
  );
}
