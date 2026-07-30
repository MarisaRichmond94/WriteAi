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

## `UNIFIED_CHROME` — retired 2026-07-30 (KAN-8)

**The flag is gone.** The values above are simply the palette now; there is no
toggle, no `data-chrome` attribute, no boot script, and no old-palette fallback.
Retired on schedule rather than becoming permanent, which is what happened to the
eight `ENABLE_*` flags in WriteAI's `.env`.

Deleted, for anyone tracing an old reference: the `[data-chrome="v2"]` blocks in
`globals.css` and `index.css`, `src/lib/unifiedChrome.ts`,
`src/components/ChromeFlagToggle.tsx`, the pre-hydration scripts in `layout.tsx`
and `index.html`, and the `⌥⇧U` handlers in both apps.

`⌥⇧U` is free again. `⌥⇧1` still toggles the sidebar in both.

### What retirement flushed out

**Hardcoded old-accent values become permanently wrong at exactly this moment.**
While the flag existed they were merely wrong-when-flagged; once the new accent
is the only accent, they are simply wrong. Three were found in WriteAI and fixed:
`.prose-dark code` and `.prose-dark blockquote` in `index.css`, and an
`accent-[#7c6af7]` arbitrary value in `ReviewPane`.

Worth repeating the rule below: grep for the *old* literals whenever a palette
becomes the default, not just when it is introduced.

## Metrics

The colour contract above got the two apps most of the way to reading as one
product. This is the remainder: type, icon and control sizes.

It exists because KAN-7's acceptance criterion said *"match Loom's within the
shared spec"* — and no such spec existed for sizes, so matching was done by eye,
one control at a time. That reaches roughly 80% and stalls.

**Loom's header is the reference.** Where the two disagreed, Loom's value wins,
with two deliberate roundings noted below.

### Typography

| Role | Stack |
|------|-------|
| Content | **Inter**, falling back to `system-ui, sans-serif` |
| Chrome — header and app furniture | **`system-ui`**, `-apple-system, sans-serif` |

**The split is deliberate, not an oversight.** Inter in the header "doesn't look
quite right" — chrome reads better in the native UI face, while body content
carries the branded one. Both apps apply the same rule, so this is a shared
decision rather than Loom simply never having declared a font.

Expose it as a `font-chrome` utility in both apps so the intent is legible at the
call site, rather than a bare `font-[system-ui]`.

- **Loom** loads Inter via `next/font/google` with `variable: '--font-inter'` —
  self-hosted, no layout shift, no external request.
- **WriteAI** already loads Inter from Google Fonts in `index.html`.

### Header

| Element | Value |
|---------|-------|
| Padding | `px-6 py-3` |
| Identity cluster gap | `gap-3` (12px) |
| Logo | 36px (`h-9 w-9`) |
| Project title | 20px, weight 400, `tracking-wider` |
| Greeting | 14px (`text-sm`), **plus `mr-2`** — see below |
| Avatar | 40px (`w-10 h-10`) with **`border-2`**, not `ring` — see below |
| Icon-button glyph | 16px |
| Icon-button padding | `p-1` → a 24px control around a 16px glyph |
| Light-toggle sun/moon | 14px |
| App-switch (sparkles) | 14px |

### Sizes alone are not enough

Three mismatches survived the first pass at this contract because they are about
*treatment*, not measurement. Matching numbers is necessary and insufficient.

**Avatar — border, never ring.** Both apps read `w-10 h-10`, yet WriteAI's
rendered visibly larger: `ring-1` is a box-shadow drawn **outside** the element,
so a 40px avatar occupied 42px, while Loom's `border-2` draws **inside**. Use
`border-2 border-accent/30 hover:border-accent`.

**Font smoothing.** WriteAI's `<body>` carried `antialiased`
(`-webkit-font-smoothing: antialiased`) and Loom's did not. The same face renders
noticeably thinner under it on macOS — enough to read as a different font even
when the stack is identical. Neither app sets it now.

**Greeting trailing margin.** Loom's greeting carries `mr-2` on top of the
cluster's `gap-3`, giving 20px before the light toggle where every other gap is
12px. Inherited rather than designed, but it is what Loom looks like today and
Loom is the reference, so WriteAI matches it. Worth revisiting if the cluster is
ever tidied — at which point remove it from **both**.

### Copy

**Greeting is sentence case**: "Good afternoon, …", not "Good Afternoon, …".
WriteAI title-cased the period, which reads as a proper noun.

### Sidebar

| | |
|---|---|
| Width | 224px (`w-56`) |

### Two roundings, on purpose

Loom used `size={13}` for the toggle icons and `size={15}` for the bell. Neither
maps to a Tailwind step, and the two apps address icons differently — Loom via
`react-icons` `size={n}` in pixels, WriteAI via `lucide-react` and Tailwind
classes. A shared value has to be expressible in both.

- Toggle icons **13 → 14px** (`h-3.5` / `size={14}`)
- Bell **15 → 16px** (`h-4` / `size={16}`)

Loom shifts by a pixel in each case; the alternative is a contract WriteAI cannot
express.

### Icon-button ratio

**Size the control to its glyph.** WriteAI's bell was `h-8 w-8` (32px) around a
16px icon — 8px of dead space per side. Absolutely-positioned children such as
the unread badge anchor to the *button* edge, so they drifted away from the glyph
and crowded the neighbouring control.

KAN-1 patched that at the badge with flush positioning; the ratio is the actual
cause. With `p-1`, badge offsets converge on Loom's `-top-1 -right-1` in both
apps rather than needing per-control compensation.

### Rule

No hardcoded sizes at a call site where a token exists — the same rule the colour
contract carries. If a value here changes, it changes in one place per app.

## Always-dark chrome

Some chrome must stay dark **inside** light mode: the chapter editor's sticky
footer and its skeleton, which mirror the reader's bars. The reader gets this
free by living outside the `light-body` wrapper; those two do not.

`.light-body` redefines `--color-*`, so `var(--color-ink)` inside it resolves
*light*. `--dark-*` is a parallel reference light mode never touches, and
`.chrome-dark` maps the theme tokens back onto it:

```css
.chrome-dark {
  --color-surface-raised: var(--dark-surface-raised);
  /* …ink, ink-muted, ink-faint, surface-muted */
}
```

Descendants then use ordinary `bg-surface-raised` / `text-ink` utilities. Use
this class instead of inlining dark hexes — that is what previously pinned that
chrome to the old palette regardless of the flag.

**`--dark-*` must be kept in step with `--color-*` in both token blocks.** They
are declared adjacently for exactly that reason. KAN-8 removes half of this when
it collapses the flag.

## Rule: no hardcoded colour literals

Every colour must resolve through a token, so the palette stays a few-values
edit.

**Check three places, not one.** KAN-6 grepped `globals.css` only and declared
the rule satisfied; KAN-17 then found colours the flag could not reach in two
places that grep never looked at:

1. **Stylesheets** — `globals.css`, `index.css`.
2. **Inline styles in components** — `style={{ … }}` and inline CSS-variable
   overrides. This is where the chapter footer and skeleton hid.
3. **Generated HTML strings** — markup built for a *different* document, which
   CSS variables cannot reach at all. `useWriteAiReview` opens a popup splash
   via `document.write`; it now resolves the token with `getComputedStyle` and
   interpolates the value.

Fixed across KAN-6 and KAN-17:

- `body` hardcoded `background-color: #0d0d18; color: #e0d9c8` — the page
  background could never have followed the palette
- the `.footnote-ref::after` tooltip hardcoded background, ink, and border
- `.character-ref` and `.narration-word.is-active` referenced
  `--color-accent-rgb`, **which is defined nowhere** — the literal fallback was
  always what rendered. A dead var reference reads as tokenised while behaving
  like a hardcode.
- the chapter footer and `ChapterSkeleton` inlined dark hexes (now `.chrome-dark`)
- `ReaderView`'s character card hardcoded its dark palette
- the `useWriteAiReview` splash background

Acceptance grep — should return hits only inside token definitions:

```sh
grep -rn "#0d0d18\|#12121e\|#1a1a2e\|#1e1e3a\|#e0d9c8" src/
```

### Accepted remainders

- **`ReaderView`'s character card keeps its *light*-mode literals**
  (`#ffffff`, `#d4d0c8`, `#ede9e0`, `#1a1a2a`). The card renders outside the
  `light-body` wrapper, so it cannot inherit the page theme and must branch on
  `lightMode` by hand. Its light palette is bespoke and not covered by the token
  set. Light mode is unchanged by the flag, so these are inert — but they are a
  genuine remaining inconsistency, not an oversight.
- **`useWriteAiReview`'s `#9ca3af`** body text and its `#111` emergency
  fallback. Neither is a palette value; the fallback is deliberately neutral so
  it cannot go stale the way a copied token would.
