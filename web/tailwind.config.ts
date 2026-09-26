import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#f5f7fb",
        ink: { DEFAULT: "#0f172a", soft: "#334155", muted: "#64748b", faint: "#94a3b8" },
        line: "#e6e9f0",
        brand: { 50: "#ecfdf8", 100: "#d1faec", 200: "#a7f3d9", 400: "#2dd4ae", 500: "#10b996", 600: "#0a9a7d", 700: "#0b7a65", 900: "#073b33" },
        night: { 900: "#0a1020", 800: "#111a2e", 700: "#1a2540", 600: "#26324f" },
        met: "#059669",
        attention: "#d97706",
        gap: "#e11d48",
      },
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        display: ["'Plus Jakarta Sans'", "Inter", "system-ui", "sans-serif"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(15,23,42,0.04), 0 4px 16px -4px rgba(15,23,42,0.06)",
        lift: "0 10px 30px -10px rgba(15,23,42,0.25)",
      },
      borderRadius: { xl: "14px", "2xl": "18px" },
    },
  },
  plugins: [],
} satisfies Config;
