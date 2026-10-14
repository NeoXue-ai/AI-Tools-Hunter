/** @type {import('tailwindcss').Config} */

// Semantic tokens resolve to CSS variables so one `.dark` class flips the
// whole console. Channels are space-separated RGB so Tailwind's `<alpha-value>`
// (and therefore `bg-surface/60`) keeps working.
const token = (name) => `rgb(var(--dh-${name}) / <alpha-value>)`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        canvas: token("canvas"),
        surface: token("surface"),
        raised: token("raised"),
        sunken: token("sunken"),
        line: token("line"),
        "line-strong": token("line-strong"),
        ink: token("ink"),
        "ink-2": token("ink-2"),
        "ink-3": token("ink-3"),
        accent: token("accent"),
        "accent-ink": token("accent-ink"),
        "accent-soft": token("accent-soft"),
        fresh: token("fresh"),
        warm: token("warm"),
        dead: token("dead"),
        slatey: token("slatey"),
      },
      fontFamily: {
        sans: [
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          '"PingFang SC"',
          '"Hiragino Sans GB"',
          '"Microsoft YaHei"',
          "Roboto",
          "Helvetica",
          "Arial",
          "sans-serif",
        ],
        mono: [
          "ui-monospace",
          "SFMono-Regular",
          '"SF Mono"',
          "Menlo",
          "Consolas",
          '"Liberation Mono"',
          "monospace",
        ],
      },
      fontSize: {
        "2xs": ["0.6875rem", { lineHeight: "1rem" }],
      },
      borderRadius: {
        card: "0.625rem",
      },
      boxShadow: {
        card: "0 1px 2px rgb(var(--dh-shadow) / 0.05), 0 0 0 1px rgb(var(--dh-line) / 1)",
        lift: "0 8px 24px -8px rgb(var(--dh-shadow) / 0.18), 0 0 0 1px rgb(var(--dh-line-strong) / 1)",
        pop: "0 24px 64px -16px rgb(var(--dh-shadow) / 0.32), 0 0 0 1px rgb(var(--dh-line-strong) / 1)",
      },
      transitionTimingFunction: {
        out: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
      keyframes: {
        "rise-in": {
          from: { opacity: "0", transform: "translateY(6px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "fade-in": {
          from: { opacity: "0" },
          to: { opacity: "1" },
        },
        "slide-in-right": {
          from: { opacity: "0", transform: "translateX(12px)" },
          to: { opacity: "1", transform: "translateX(0)" },
        },
        "drawer-up": {
          from: { opacity: "0", transform: "translateY(24px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        sweep: {
          "0%": { transform: "translateX(-100%)" },
          "100%": { transform: "translateX(200%)" },
        },
        "pulse-ring": {
          "0%": { opacity: "0.55", transform: "scale(1)" },
          "70%, 100%": { opacity: "0", transform: "scale(2.4)" },
        },
      },
      animation: {
        "rise-in": "rise-in 0.28s cubic-bezier(0.16, 1, 0.3, 1) both",
        "fade-in": "fade-in 0.2s ease-out both",
        "slide-in-right": "slide-in-right 0.24s cubic-bezier(0.16, 1, 0.3, 1) both",
        "drawer-up": "drawer-up 0.3s cubic-bezier(0.16, 1, 0.3, 1) both",
        sweep: "sweep 1.5s ease-in-out infinite",
        "pulse-ring": "pulse-ring 1.8s ease-out infinite",
      },
    },
  },
  plugins: [],
};
