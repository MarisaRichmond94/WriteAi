import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          DEFAULT: "#0f1117",
          card: "#1a1d27",
          hover: "#21253a",
          border: "#2a2d3a",
        },
        accent: {
          DEFAULT: "#7c6af7",
          hover: "#6b59e8",
          muted: "#4a3fa6",
          subtle: "#2a2550",
        },
        ink: {
          primary: "#e8eaf0",
          secondary: "#9da3b4",
          muted: "#5c627a",
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
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      animation: {
        "pulse-slow": "pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
    },
  },
  plugins: [],
} satisfies Config;
