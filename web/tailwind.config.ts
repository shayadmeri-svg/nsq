import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        canvas: "#f7f9fc",
        ink: { DEFAULT: "#0b1324", soft: "#334155", muted: "#64748b", faint: "#94a3b8" },
        line: "#e6eaf0",
        gold: { 50: "#ecfeff", 100: "#cffafe", 200: "#a5f3fc", 300: "#67e8f9", 400: "#22c3dd", 500: "#06a7c4", 600: "#0b88a3", 700: "#0e6b80" }, // accent (cyan-teal),
        brand: { 50: "#ecfdf8", 100: "#d1faec", 200: "#a7f3d9", 400: "#2dd4ae", 500: "#10b996", 600: "#0a9a7d", 700: "#0b7a65", 900: "#073b33" },
        night: { 900: "#0b1020", 800: "#121a2e", 700: "#1b2540", 600: "#27324f" },
        met: "#059669",
        attention: "#d97706",
        gap: "#e11d48",
      },
      fontFamily: {
        sans: ["Geist", "Inter", "system-ui", "sans-serif"],
        display: ["Geist", "Inter", "system-ui", "sans-serif"],
        mono: ["'Geist Mono'", "ui-monospace", "monospace"],
      },
      boxShadow: {
        card: "0 1px 2px rgba(11,19,36,0.04), 0 2px 8px -2px rgba(11,19,36,0.04)",
        hover: "0 1px 2px rgba(11,19,36,0.05), 0 14px 32px -14px rgba(11,19,36,0.16)",
        lift: "0 18px 40px -16px rgba(11,19,36,0.28)",
        glow: "0 0 0 1px rgba(6,167,196,0.25), 0 10px 30px -12px rgba(6,167,196,0.30)",
      },
      borderRadius: { xl: "14px", "2xl": "18px" },
    },
  },
  plugins: [],
} satisfies Config;
