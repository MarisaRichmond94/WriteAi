import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // RGB-channel CSS variables so the page body can flip to light mode
        // (.light-body) while opacity modifiers like text-ink-muted/50 keep
        // working. Dark values live in :root in index.css.
        surface: {
          DEFAULT: "rgb(var(--surface) / <alpha-value>)",
          card: "rgb(var(--surface-card) / <alpha-value>)",
          hover: "rgb(var(--surface-hover) / <alpha-value>)",
          border: "rgb(var(--surface-border) / <alpha-value>)",
        },
        // Accent moved from literals to RGB-channel vars (KAN-6) so
        // UNIFIED_CHROME can swap it at runtime, the way surfaces and ink
        // already can. The channel form is also what keeps `bg-accent/10` and
        // `ring-accent` opacity modifiers working.
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          hover: "rgb(var(--accent-hover) / <alpha-value>)",
          muted: "rgb(var(--accent-muted) / <alpha-value>)",
          subtle: "rgb(var(--accent-subtle) / <alpha-value>)",
        },
        ink: {
          primary: "rgb(var(--ink-primary) / <alpha-value>)",
          secondary: "rgb(var(--ink-secondary) / <alpha-value>)",
          muted: "rgb(var(--ink-muted) / <alpha-value>)",
        },
        mode: {
          plot: "#f87171",
          timeline: "#60a5fa",
          character: "#34d399",
          alternate: "#f59e0b",
        },
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        // Chrome stays on the native UI face while content uses Inter — both
        // apps carry this split (KAN-21, TOKENS.md).
        chrome: ["system-ui", "-apple-system", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      animation: {
        "pulse-slow": "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
