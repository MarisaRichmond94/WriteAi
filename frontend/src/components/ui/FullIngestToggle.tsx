// Opt-in control shown inside the sync confirm modals. Off = incremental sync
// (only chapters that changed since the last run); on = full re-embed +
// re-extract from scratch, which incurs the full AI extraction cost.
export default function FullIngestToggle({ checked, onChange, scope }: {
  checked: boolean;
  onChange: (v: boolean) => void;
  scope: string;   // "all books" / a quoted book title — used in the helper text
}) {
  return (
    <label className="flex cursor-pointer items-start gap-2.5 rounded-md border border-surface-border bg-surface p-3">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 accent-accent"
      />
      <span className="text-[11px] leading-relaxed text-ink-secondary">
        <span className="font-semibold text-ink-primary">Full re-index</span> — re-process
        every chapter in {scope} from scratch, even unchanged ones. Much slower and incurs the
        full AI extraction cost. Leave off to sync only what changed since the last run.
      </span>
    </label>
  );
}
