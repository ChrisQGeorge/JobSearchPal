import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Muted retro-corporate palette — dingy gold + alarm orange on dark neutrals.
        // Values live in CSS variables (globals.css :root) so a page can
        // re-skin the whole UI — The Tower swaps in a pixel palette.
        corp: {
          bg: "rgb(var(--corp-bg) / <alpha-value>)",
          surface: "rgb(var(--corp-surface) / <alpha-value>)",
          surface2: "rgb(var(--corp-surface2) / <alpha-value>)",
          border: "rgb(var(--corp-border) / <alpha-value>)",
          text: "rgb(var(--corp-text) / <alpha-value>)",
          muted: "rgb(var(--corp-muted) / <alpha-value>)",
          accent: "rgb(var(--corp-accent) / <alpha-value>)",    // dingy corporate gold
          accent2: "rgb(var(--corp-accent2) / <alpha-value>)",  // warning-orange
          ok: "rgb(var(--corp-ok) / <alpha-value>)",
          danger: "rgb(var(--corp-danger) / <alpha-value>)",
        },
      },
      fontFamily: {
        sans: ["ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "Menlo", "Consolas", "monospace"],
      },
    },
  },
  plugins: [],
};

export default config;
