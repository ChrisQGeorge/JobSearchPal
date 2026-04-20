import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // Muted retro-corporate palette — dingy gold + alarm orange on dark neutrals.
        corp: {
          bg: "#0f1117",
          surface: "#161a22",
          surface2: "#1f2430",
          border: "#2a3040",
          text: "#e6e6e6",
          muted: "#8a94a6",
          accent: "#e8c468",    // dingy corporate gold
          accent2: "#ff7a45",   // warning-orange
          ok: "#6fbf73",
          danger: "#d35656",
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
