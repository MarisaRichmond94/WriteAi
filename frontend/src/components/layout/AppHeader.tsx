import { clsx } from "clsx";
import { Moon, Sun } from "lucide-react";
import { useAppStore } from "../../store/useAppStore";
import NotificationBell from "../notifications/NotificationBell";

/**
 * WriteAI's header (KAN-7) — mirrors Loom's AppHeader anatomy.
 *
 *   [ logo ] [ project / brand ]  ...  [ tools ] [ identity ]
 *
 * The identity cluster is greeting → light toggle → bell → avatar, in that
 * order, matching Loom exactly.
 *
 * This replaces a control cluster that was absolutely positioned over the main
 * pane (`absolute right-6 top-5`). Floating over content meant there was nowhere
 * to put page context or the project switcher, and it overlapped panes at narrow
 * widths.
 *
 * Note it spans the FULL width, above the sidebar — as Loom's does. The old
 * cluster lived inside <main>, so it started to the right of the sidebar. Full
 * width is what makes the two apps read as one product rather than two that
 * happen to share colours.
 *
 * The brand slot shows the site name. Loom shows the active project here; WriteAI
 * gains that in KAN-3, once KAN-10 gives it a project concept to switch between.
 * Until then this slot is the brand, which is why the two headers will look
 * asymmetric for a while — expected, not a defect.
 */

function WriterAvatar() {
  const { appSettings, setActivePane } = useAppStore();

  // settings not loaded yet: skeleton circle, no "W" initials flash
  if (appSettings === null) {
    return <span className="h-8 w-8 flex-shrink-0 animate-pulse rounded-full bg-surface-hover ring-1 ring-surface-border" />;
  }

  const name = appSettings.writer_name || "Writer";
  const photoUrl = appSettings.writer_photo_url ?? null;

  const initials = name.trim()
    ? name.trim().split(" ").map((w: string) => w[0]).slice(0, 2).join("").toUpperCase()
    : "W";

  return (
    <button
      onClick={() => setActivePane("settings")}
      // The avatar is the only way into settings (the redundant gear beside it
      // is gone, KAN-1), so the tooltip names the destination rather than the
      // writer — matching Loom's AvatarButton. The name is already on screen in
      // the greeting immediately to the left.
      title="Settings"
      aria-label="Settings"
      className="h-8 w-8 flex-shrink-0 rounded-full overflow-hidden ring-1 ring-surface-border hover:ring-accent transition-all"
    >
      {photoUrl ? (
        <img src={photoUrl} alt={name} className="h-full w-full object-cover" />
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-accent/20 text-[10px] font-semibold text-accent">
          {initials}
        </div>
      )}
    </button>
  );
}

function timeOfDay(): string {
  const h = new Date().getHours();
  if (h >= 5 && h < 12) return "Morning";
  if (h >= 12 && h < 18) return "Afternoon";
  return "Evening";
}

type Props = {
  lightMode: boolean;
  onToggleLightMode: () => void;
};

export default function AppHeader({ lightMode, onToggleLightMode }: Props) {
  const { appSettings, siteName } = useAppStore();

  return (
    <nav className="flex-shrink-0 flex items-center gap-3 border-b border-surface-border bg-surface-card px-6 py-3 text-sm">
      <img src="/logo.svg" alt="" className="block h-9 w-9 flex-shrink-0" />
      {/* Matches Loom's project title exactly: ink at 400, xl, wide tracking —
          NOT accent/bold, which is the treatment Loom's wordmark used to have
          before it became a title. ink-primary is WriteAI's name for the token
          Loom calls ink; the two resolve to the same value (TOKENS.md). */}
      <span className="text-ink-primary font-normal tracking-wider text-xl leading-none flex-shrink-0 truncate max-w-[420px]">
        {siteName}
      </span>

      <div className="ml-auto flex items-center gap-3 flex-shrink-0">
        {appSettings === null ? (
          <span className="h-3.5 w-40 animate-pulse rounded bg-surface-hover" />
        ) : (
          <span className="text-xs text-ink-primary whitespace-nowrap">
            Good {timeOfDay()}, {appSettings.writer_name || "Writer"}
          </span>
        )}

        {/* Icon buttons are sized to their glyph rather than padded out to 32px
            (KAN-7). The bell used to be h-8 w-8 around a 16px icon — 8px of dead
            space per side — so its unread badge, which anchors to the BUTTON
            edge, drifted away from the glyph and crowded the avatar. Fixing the
            ratio is what lets badge offsets match Loom's instead of needing a
            per-control compensation. */}
        <button
          role="switch"
          aria-checked={lightMode}
          onClick={onToggleLightMode}
          title={lightMode ? "Switch to dark mode" : "Switch to light mode"}
          className="flex items-center gap-1.5 text-ink-muted hover:text-ink-primary transition-colors"
        >
          <Moon className="h-3 w-3" />
          <span className={clsx(
            "relative inline-flex w-9 h-5 rounded-full transition-colors duration-200",
            lightMode ? "bg-accent" : "bg-surface-hover"
          )}>
            <span className={clsx(
              "absolute top-0.5 w-4 h-4 rounded-full bg-white shadow transition-all duration-200",
              lightMode ? "left-4" : "left-0.5"
            )} />
          </span>
          <Sun className="h-3 w-3" />
        </button>

        <NotificationBell />
        <WriterAvatar />
      </div>
    </nav>
  );
}
