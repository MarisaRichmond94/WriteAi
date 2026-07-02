import { Database } from "lucide-react";
import { clsx } from "clsx";
import { useAppStore } from "../../store/useAppStore";

export default function IndexStatusBar() {
  const { indexStatus } = useAppStore();

  if (!indexStatus) {
    return (
      <div className="flex items-center gap-2 text-[10px] text-ink-muted">
        <Database className="h-3 w-3" />
        <span>Index not loaded</span>
      </div>
    );
  }

  return (
    <div className="space-y-1">
      <div className="flex items-center gap-2 text-[10px] text-ink-muted">
        <div
          className={clsx(
            "h-1.5 w-1.5 rounded-full",
            indexStatus.is_ready ? "bg-green-400" : "bg-yellow-400"
          )}
        />
        <span>
          {indexStatus.is_ready
            ? `${indexStatus.total_chunks.toLocaleString()} chunks indexed`
            : "Index not ready"}
        </span>
      </div>
    </div>
  );
}
