# Loom ↔ WriteAI design token contract

The canonical palette both apps share. If you change a value here, change it in
the other repo too — WriteAI has a mirror of this file, same as `INTEGRATION.md`.

> **Status:** behind the `UNIFIED_CHROME` flag (KAN-6). Flag off renders each
> app's pre-unification palette untouched, so the old look stays available as a
> comparison baseline for all of Phase A.

## The deliberate design decision

**Values are shared. Names are not.**

Each app keeps its own token names; both resolve to the same values. That is the
whole point — the names are invisible to the writer, and 49 Loom files plus 45
WriteAI files reference them. Renaming would mean ~94 files of mechanical churn
for zero visual difference, in a codebase that guards a novel. Tailwind also
drops unknown classes *silently*, so a missed rename shows up as an unstyled
element rather than a build error.

Unifying values got the entire visual result by editing two files.

## Canonical dark palette

| Role | Value | Loom token | WriteAI token |
|------|-------|-----------|---------------|
| Page background | `#0F1117` | `surface-base` | `surface` |
| Panels, cards, sidebar | `#1A1D27` | `surface-raised` | `surface-card` |
| Overlays, hover states | `#21253A` | `surface-overlay` | `surface-hover` |
| Skeletons, borders | `#2A2D3A` | `surface-muted` | `surface-border` |
| Primary ink | `#E8EAF0` | `ink` | `ink-primary` |
| Secondary ink | `#9DA3B4` | `ink-muted` | `ink-secondary` |
| Faint ink | `#5C627A` | `ink-faint` | `ink-muted` |
| Accent | `#8888FF` | `accent` | `accent` |
| Accent hover | `#7777F0` | — | `accent-hover` |
| Accent muted | `#4A4A7A` | `accent-muted` | `accent-muted` |
| Accent subtle | `#2A2A55` | — | `accent-subtle` |

**Note the ink-token trap.** `ink-muted` means *different things* in the two
apps — Loom's is the secondary tier (`#9DA3B4`), WriteAI's is the faintest
(`#5C627A`). This is the strongest argument for eventually renaming, and the
sharpest hazard when copying markup between the apps.

## Light palette

**Already identical, and unchanged by the flag.** Loom's `.light-body` hexes and
WriteAI's `.light-body` channel values were the same values before this work
began — WriteAI borrowed them from Loom. Only dark mode diverged.

| Role | Value |
|------|-------|
| Page background | `#F5F2EB` |
| Panels | `#EDE9E0` |
| Overlays | `#E5E0D5` |
| Skeletons/borders | `#DDD8CC` |
| Primary ink | `#1A1A2A` |
| Secondary ink | `#444444` |
| Faint ink | `#888888` |

Both apps deliberately apply light mode to the **page body only** — the sidebar
stays dark. Preserve that.

## Decisions, and why

- **Accent `#8888FF` (Loom's).** Chosen over WriteAI's `#7c6af7`.
- **Surfaces and ink: WriteAI's cool ramp.** Loom's dark palette was
  violet-tinted (`#0d0d18` → `#1e1e3a`) with warm cream ink (`#e0d9c8`); WriteAI's
  is neutral blue-grey with cool ink. Cool won, so Loom moved.
- **Loom's warm ink was rejected, not forgotten.** It was only *half* warm:
  primary was cream but the muted and faint tiers were pure neutral grey
  (`#aaa`, `#666`). Going warm properly would have meant inventing warm lower
  tiers (roughly `#ADA698` / `#68635A`). Recorded here in case the decision is
  ever revisited.
- **Surfaces map by position**, so Loom's existing light-to-dark hierarchy
  survives while the hue changes: `base→surface`, `raised→card`,
  `overlay→hover`, `muted→border`.

## Known remaining divergence

**Borders.** WriteAI has a dedicated `surface-border` token. Loom has none — it
draws borders as `border-accent/10` and `border-accent/20`, i.e. the accent at
low opacity, which reads as a faint violet edge rather than a neutral grey one.

Deliberately **not** changed here: it would touch dozens of Loom files and is a
visual-design question, not a token question. It belongs to KAN-2 when the
header is rebuilt. Until then the two apps' borders differ in character even
with identical tokens.

## Out of scope

Loom's `--color-choice-*` palette (six choice-type colours for the
choose-your-own-adventure blocks) is domain-specific, has no WriteAI equivalent,
and is untouched. Likewise WriteAI's `mode.*` colours.

WriteAI's `index.css` also carries ~30 hand-written
`.light-body .text-{color}-{shade}` overrides that deepen pill and status text
for the light palette. Those are **light-mode only**, and this work changed dark
mode only, so they are unaffected.

## Iconography

**Deliberately deferred.** Loom imports from `react-icons/lu`, WriteAI from
`lucide-react` — but `react-icons/lu` *is* Lucide, so the two apps already render
identical glyphs. Migrating either direction touches dozens of files for zero
visual change, and the size APIs differ (`size={15}` vs `className="h-4 w-4"`;
15px has no exact Tailwind step), so every call site would need visual checking.

New shared code should pick one package. Existing code stays.

Exception worth knowing: WriteAI's sidebar uses `FaTimeline` from
`react-icons/fa6`, which has no Lucide equivalent.

## The flag

| | Loom | WriteAI |
|---|---|---|
| Attribute | `data-chrome="v2"` on `<html>` | same |
| Primary switch | `localStorage['loom-unified-chrome']` | `localStorage['writeai-unified-chrome']` |
| Build default | `NEXT_PUBLIC_UNIFIED_CHROME` | none — defaults off |
| Toggle | `⌥⇧U` | `⌥⇧U` |

**`localStorage` is the primary switch, not the env var.** Next.js inlines
`NEXT_PUBLIC_*` at build time and both apps run production builds under launchd,
so flipping an env var appears to do nothing until a rebuild.

WriteAI's flag is client-side only, on purpose: routing a short-lived UI flag
through FastAPI's `/api/settings` would add backend plumbing that gets deleted
at retirement anyway.

Both apps apply the flag via a pre-hydration inline script in `<head>`, so the
palette is settled before first paint instead of flashing the old one. This is
the same selector-override technique `.light-body` already uses in both apps —
not new machinery.

### Retirement — owned by KAN-8

When the navigation model is settled there is nothing left to compare. Delete:

- `[data-chrome="v2"]` blocks in `globals.css` and `index.css`, promoting their
  values into `@theme` / `:root`
- `src/lib/unifiedChrome.ts` and `src/components/ChromeFlagToggle.tsx` (Loom)
- the inline script in `layout.tsx` (Loom) and `index.html` (WriteAI)
- the `⌥⇧U` branch in `AppShell.tsx` (WriteAI)
- `NEXT_PUBLIC_UNIFIED_CHROME` from any `.env`

## Rule: no hardcoded colour literals

Every colour must resolve through a token, so the palette stays a
few-values edit. Two literals were found and fixed during KAN-6, both in Loom's
`globals.css`:

- `body` hardcoded `background-color: #0d0d18; color: #e0d9c8`, which would have
  left the page background on the old palette no matter what the flag said
- the `.footnote-ref::after` tooltip hardcoded its background, ink, and an
  `rgba(136,136,255,0.2)` border

Grep for `#[0-9a-fA-F]{3,6}` outside the token blocks before calling this done.
