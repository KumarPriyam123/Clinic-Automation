import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Calm clinical palette (see CLAUDE.md panel principles)
        primary: "#0f766e", // deep teal
      },
    },
  },
  plugins: [],
};

export default config;
