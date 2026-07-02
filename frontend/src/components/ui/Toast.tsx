import { useEffect } from "react";
import { X } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";

export default function Toast() {
  const { toastMessage, clearToast } = useAppStore();

  useEffect(() => {
    if (!toastMessage) return;
    const timer = setTimeout(clearToast, 4000);
    return () => clearTimeout(timer);
  }, [toastMessage, clearToast]);

  if (!toastMessage) return null;

  return (
    <div className="fixed bottom-6 right-6 z-50 flex items-center gap-3 rounded-lg border border-surface-border bg-surface-card px-4 py-3 shadow-xl shadow-black/40 max-w-sm">
      <p className="flex-1 text-sm text-ink-primary">{toastMessage}</p>
      <button
        onClick={clearToast}
        className="flex-shrink-0 text-ink-muted hover:text-ink-primary transition-colors"
      >
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
