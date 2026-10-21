import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#f6f4ef",
        ink: { DEFAULT: "#101827", soft: "#334155", muted: "#667085", faint: "#98a2b3" },
        line: "#e9e5dc",
        gold: { 50: "#fbf7ec", 100: "#f5ecd3", 200: "#ead8a8", 300: "#ddbf78", 400: "#d4b26a", 500: "#b8923f", 600: "#94722c", 700: "#6f5420" },
        brand: { 50: "#ecfdf8", 100: "#d1faec", 200: "#a7f3d9", 400: "#2dd4ae", 500: "#10b996", 600: "#0a9a7d", 700: "#0b7a65", 900: "#073b33" },
        night: { 900: "#0b1020", 800: "#121a2e", 700: "#1b2540", 600: "#27324f" },
        met: "#059669",
        attention: "#d97706",
        gap: "#e11d48",
      },
      fontFamily: {
        sans: ["Manrope", "system-ui", "sans-serif"],
        display: ["Fraunces", "Georgia", "serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(16,24,39,0.04), 0 8px 24px -12px rgba(16,24,39,0.10)",
        lift: "0 18px 40px -16px rgba(16,24,39,0.30)",
        glow: "0 0 0 1px rgba(212,178,106,0.35), 0 10px 30px -12px rgba(184,146,63,0.35)",
      },
      borderRadius: { xl: "14px", "2xl": "18px" },
    },
  },
  plugins: [],
} satisfies Config;
