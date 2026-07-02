import { ReactNode, useEffect } from "react";
import { createPortal } from "react-dom";
import clsx from "clsx";
import { Loader2, X, AlertTriangle, CheckCircle2, Info } from "lucide-react";
import { useApp } from "../store";

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx("animate-spin", className ?? "h-4 w-4")} strokeWidth={1.5} />;
}

export function Modal({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={onClose}>
      <div
        className={clsx(
          "max-h-[85vh] overflow-y-auto rounded-xl border border-surface-border bg-surface-card p-6 shadow-2xl",
          wide ? "w-[720px] max-w-[92vw]" : "w-[440px] max-w-[92vw]",
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink-primary">{title}</h2>
          <button onClick={onClose} className="rounded-md p-1 text-ink-secondary hover:text-ink-primary">
            <X className="h-4 w-4" strokeWidth={1.5} />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  );
}

export function Button({
  children,
  onClick,
  variant = "primary",
  disabled,
  className,
}: {
  children: ReactNode;
  onClick?: () => void;
  variant?: "primary" | "secondary" | "danger" | "text";
  disabled?: boolean;
  className?: string;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={clsx(
        "inline-flex items-center gap-1.5 rounded-md px-4 py-2 text-xs font-medium transition-colors duration-150",
        variant === "primary" && "bg-accent text-white hover:bg-accent-hover",
        variant === "secondary" && "border border-surface-border text-ink-primary hover:border-accent",
        variant === "danger" && "border border-rose-500/40 text-rose-300 hover:bg-rose-500/10",
        variant === "text" && "px-2 py-1 text-ink-secondary hover:text-ink-primary",
        disabled && "cursor-not-allowed opacity-50",
        className,
      )}
    >
      {children}
    </button>
  );
}

export function EmptyState({
  icon,
  title,
  hint,
  action,
}: {
  icon: ReactNode;
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-10 text-center">
      <div className="text-ink-muted">{icon}</div>
      <div className="text-sm font-medium text-ink-primary">{title}</div>
      {hint && <div className="max-w-sm text-xs text-ink-secondary">{hint}</div>}
      {action}
    </div>
  );
}

export function SectionLabel({ children }: { children: ReactNode }) {
  return (
    <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">{children}</div>
  );
}

export function Toasts() {
  const { toasts, dismissToast } = useApp();
  if (!toasts.length) return null;
  const icons = {
    info: <Info className="h-4 w-4 text-sky-300" strokeWidth={1.5} />,
    error: <AlertTriangle className="h-4 w-4 text-rose-300" strokeWidth={1.5} />,
    success: <CheckCircle2 className="h-4 w-4 text-emerald-300" strokeWidth={1.5} />,
  };
  return createPortal(
    <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className="flex items-center gap-2 rounded-lg border border-surface-border bg-surface-card px-4 py-2.5 text-xs text-ink-primary shadow-xl"
        >
          {icons[t.kind]}
          <span className="max-w-xs">{t.message}</span>
          <button onClick={() => dismissToast(t.id)} className="ml-2 text-ink-muted hover:text-ink-primary">
            <X className="h-3.5 w-3.5" strokeWidth={1.5} />
          </button>
        </div>
      ))}
    </div>,
    document.body,
  );
}

export function ConfirmModal({
  title,
  body,
  confirmLabel = "Confirm",
  onConfirm,
  onClose,
  busy,
}: {
  title: string;
  body: ReactNode;
  confirmLabel?: string;
  onConfirm: () => void;
  onClose: () => void;
  busy?: boolean;
}) {
  return (
    <Modal title={title} onClose={onClose}>
      <div className="mb-5 text-xs leading-relaxed text-ink-secondary">{body}</div>
      <div className="flex justify-end gap-2">
        <Button variant="secondary" onClick={onClose}>
          Cancel
        </Button>
        <Button onClick={onConfirm} disabled={busy}>
          {busy && <Spinner className="h-3.5 w-3.5" />}
          {confirmLabel}
        </Button>
      </div>
    </Modal>
  );
}
