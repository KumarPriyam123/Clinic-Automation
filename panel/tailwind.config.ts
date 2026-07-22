import type { Config } from "tailwindcss";

/**
 * Calm clinical palette (CLAUDE.md panel principles). One deep-teal primary,
 * soft near-white canvas, and a small fixed set of status chip colors. No
 * gradients, no showpiece accents — sober utility a tired receptionist can read
 * at a glance on a cheap Android in daylight.
 */
const config: Config = {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#f4f6f5", // soft near-white background
        surface: "#ffffff",
        line: "#e2e7e5",
        ink: "#16302c", // near-black, faint teal cast
        muted: "#5c6b67",
        faint: "#8a9995",
        primary: {
          DEFAULT: "#0f766e", // deep teal
          dark: "#0b544e",
          soft: "#e2f1ee",
          ink: "#0a3d38",
        },
        // status chips
        booked: { bg: "#fdf0d5", fg: "#8a5a00" }, // amber
        arrived: { bg: "#dcf5e4", fg: "#146c39" }, // green
        consult: { bg: "#dbeafe", fg: "#1d4ed8" }, // blue
        grace: { bg: "#ffe6d5", fg: "#9a3412" }, // warm orange
        neutral: { bg: "#e6eae8", fg: "#3f4b48" }, // gray
        danger: { DEFAULT: "#b4231f", soft: "#fbe4e2" },
      },
      fontFamily: {
        sans: [
          "var(--font-noto)",
          "Noto Sans",
          "Noto Sans Devanagari",
          "system-ui",
          "sans-serif",
        ],
      },
      spacing: {
        touch: "3.5rem", // 56px minimum touch target
        next: "4.5rem", // 72px NEXT button
      },
      boxShadow: {
        card: "0 1px 2px rgba(16,48,44,0.06), 0 1px 3px rgba(16,48,44,0.05)",
        lift: "0 -2px 16px rgba(16,48,44,0.10)",
        sheet: "0 -8px 40px rgba(16,48,44,0.18)",
      },
      borderRadius: {
        xl2: "1.25rem",
      },
      keyframes: {
        "sheet-up": {
          "0%": { transform: "translateY(100%)" },
          "100%": { transform: "translateY(0)" },
        },
        "fade-in": {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        "pop": {
          "0%": { transform: "scale(0.96)", opacity: "0" },
          "100%": { transform: "scale(1)", opacity: "1" },
        },
        "pulse-ring": {
          "0%": { boxShadow: "0 0 0 0 rgba(29,78,216,0.35)" },
          "70%": { boxShadow: "0 0 0 12px rgba(29,78,216,0)" },
          "100%": { boxShadow: "0 0 0 0 rgba(29,78,216,0)" },
        },
      },
      animation: {
        "sheet-up": "sheet-up 0.22s cubic-bezier(0.22,1,0.36,1)",
        "fade-in": "fade-in 0.18s ease-out",
        pop: "pop 0.16s ease-out",
        "pulse-ring": "pulse-ring 2.2s ease-out infinite",
      },
    },
  },
  plugins: [],
};

export default config;
