/** @type {import('tailwindcss').Config} */
module.exports = {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: {
          50:  "#f0f9ff", 100: "#e0f2fe", 200: "#bae6fd", 300: "#7dd3fc",
          400: "#38bdf8", 500: "#0ea5e9", 600: "#0284c7", 700: "#0369a1",
          800: "#075985", 900: "#0c4a6e",
        },
        surface: {
          950: "#06090f", 900: "#0b0f1a", 800: "#0f1829", 700: "#111c2d",
          600: "#162032", 500: "#1e2d42", 400: "#334155",
        },
        accent: {
          primary:   "#38bdf8",
          secondary: "#8b5cf6",
          success:   "#10b981",
          danger:    "#ef4444",
          warning:   "#f59e0b",
        },
        success: "#10b981",
        warning: "#f59e0b",
        danger:  "#ef4444",
        info:    "#38bdf8",

        // ── Semantic State tokens (mapped to CSS variables) ────────────
        state: {
          running: "var(--state-running)",
          success: "var(--state-success)",
          error:   "var(--state-error)",
          warning: "var(--state-warning)",
          idle:    "var(--state-idle)",
        },

        // ── Layer (background) tokens ──────────────────────────────────
        layer: {
          void:     "var(--bg-void)",
          base:     "var(--bg-base)",
          surface:  "var(--bg-surface)",
          elevated: "var(--bg-elevated)",
          overlay:  "var(--bg-overlay)",
          panel:    "var(--bg-panel)",
        },

        // ── Foreground / text tokens ───────────────────────────────────
        fg: {
          primary:   "var(--text-primary)",
          secondary: "var(--text-secondary)",
          tertiary:  "var(--text-tertiary)",
          muted:     "var(--text-muted)",
          code:      "var(--text-code)",
        },

        // ── Alpha-opacity variants for state colours ───────────────────
        // These allow classes like bg-state-success-bar, border-state-error-border, etc.
        "state-success-bar":    "var(--state-success-bar)",
        "state-success-wash":   "var(--state-success-wash)",
        "state-success-border": "var(--state-success-border)",
        "state-success-dim":    "var(--state-success-dim)",
        "state-error-bar":      "var(--state-error-bar)",
        "state-error-wash":     "var(--state-error-wash)",
        "state-error-border":   "var(--state-error-border)",
        "state-running-dim":    "var(--state-running-dim)",
      },

      // ── Shadow tokens ────────────────────────────────────────────────
      boxShadow: {
        "running-glow": "0 0 24px rgba(34, 211, 238, 0.12)",
        "success-node": "0 0 0 1px rgba(16, 185, 129, 0.35), 0 0 14px rgba(16, 185, 129, 0.25)",
        "error-node":   "0 0 0 1px rgba(239, 68, 68, 0.40),  0 0 14px rgba(239, 68, 68, 0.28)",
        "cyan-core":    "0 0 0 1px rgba(34, 211, 238, 0.08), 0 0 60px rgba(34, 211, 238, 0.06)",
      },

      // ── Z-index tokens ───────────────────────────────────────────────
      zIndex: {
        dropdown: "50",
        modal:    "100",
        overlay:  "200",
        toast:    "300",
      },
      fontFamily: {
        sans:    ["Inter", "system-ui", "-apple-system", "sans-serif"],
        mono:    ["JetBrains Mono", "monospace"],
        display: ["Sora", "sans-serif"],
      },
      animation: {
        "pulse-slow":        "pulse 3s cubic-bezier(0.4,0,0.6,1) infinite",
        "ping-slow":         "ping 2.5s cubic-bezier(0,0,0.2,1) infinite",
        "fade-in":           "fadeIn 0.22s ease-out",
        "fade-up":           "fadeUp 0.22s ease-out",
        "shimmer":           "shimmer 2.8s linear infinite",
        "border-pulse":      "borderPulse 2.8s ease-in-out infinite",
        "border-pulse-cyan": "borderPulseCyan 2s ease-in-out infinite",
        "ring-expand":       "ringExpand 2.4s ease-out infinite",
        "gradient":          "gradientShift 6s ease infinite",
        "float":             "float 4s ease-in-out infinite",
        "blink":             "blink 1.1s ease-in-out infinite",
        "glow-pulse":        "glowPulse 2.5s ease-in-out infinite",
        "glow-pulse-cyan":   "glowPulseCyan 2s ease-in-out infinite",
        "glow-pulse-violet": "glowPulseViolet 2.5s ease-in-out infinite",
        "glow-pulse-emerald":"glowPulseEmerald 2s ease-in-out infinite",
        "glow-pulse-red":    "glowPulseRed 0.8s ease-in-out infinite",
        "ripple":            "ripple 0.65s ease-out forwards",
        "shockwave":         "shockwave 0.5s ease-out infinite",
        "instrument-tick":   "instrumentTick 1s cubic-bezier(0.4,0,0.2,1) infinite",
        "route-enter":       "routeEnter 0.28s ease-out both",
      },
      keyframes: {
        fadeIn: {
          "0%":   { opacity: "0", transform: "translateY(4px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        fadeUp: {
          "0%":   { opacity: "0", transform: "translateY(8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          from: { backgroundPosition: "-200% center" },
          to:   { backgroundPosition:  "200% center" },
        },
        borderPulse: {
          "0%,100%": { boxShadow: "0 0 0 1px rgba(56,189,248,0.20),0 0 16px rgba(56,189,248,0.06)" },
          "50%":     { boxShadow: "0 0 0 1px rgba(56,189,248,0.50),0 0 36px rgba(56,189,248,0.20)" },
        },
        borderPulseCyan: {
          "0%,100%": { boxShadow: "0 0 0 1px rgba(56,189,248,0.15),0 0 20px rgba(56,189,248,0.08)" },
          "50%":     { boxShadow: "0 0 0 1px rgba(56,189,248,0.55),0 0 40px rgba(56,189,248,0.22),0 0 80px rgba(56,189,248,0.06)" },
        },
        ringExpand: {
          "0%":   { transform: "scale(1)",   opacity: "0.55" },
          "100%": { transform: "scale(2.6)", opacity: "0" },
        },
        gradientShift: {
          "0%,100%": { backgroundPosition: "0% 50%" },
          "50%":     { backgroundPosition: "100% 50%" },
        },
        glowPulse: {
          "0%, 100%": { opacity: "0.6" },
          "50%":      { opacity: "1.0" },
        },
        glowPulseCyan: {
          "0%,100%": { boxShadow: "0 0 8px rgba(56,189,248,0.3),  0 0 24px rgba(56,189,248,0.10)" },
          "50%":     { boxShadow: "0 0 18px rgba(56,189,248,0.65), 0 0 48px rgba(56,189,248,0.20)" },
        },
        glowPulseViolet: {
          "0%,100%": { boxShadow: "0 0 8px rgba(139,92,246,0.3),  0 0 24px rgba(139,92,246,0.10)" },
          "50%":     { boxShadow: "0 0 18px rgba(139,92,246,0.60), 0 0 44px rgba(139,92,246,0.18)" },
        },
        glowPulseEmerald: {
          "0%,100%": { boxShadow: "0 0 6px rgba(16,185,129,0.3),  0 0 18px rgba(16,185,129,0.10)" },
          "50%":     { boxShadow: "0 0 14px rgba(16,185,129,0.60), 0 0 36px rgba(16,185,129,0.18)" },
        },
        glowPulseRed: {
          "0%,100%": { boxShadow: "0 0 8px rgba(239,68,68,0.4),   0 0 24px rgba(239,68,68,0.15)" },
          "50%":     { boxShadow: "0 0 22px rgba(239,68,68,0.75), 0 0 56px rgba(239,68,68,0.25)" },
        },
        ripple: {
          "0%":   { transform: "scale(0.85)", opacity: "0.9" },
          "100%": { transform: "scale(2.0)",  opacity: "0" },
        },
        shockwave: {
          "0%":   { transform: "scale(1)",    opacity: "0.8",  boxShadow: "0 0 0 2px rgba(239,68,68,0.6)" },
          "50%":  { transform: "scale(1.15)", opacity: "0.4",  boxShadow: "0 0 0 6px rgba(239,68,68,0.2)" },
          "100%": { transform: "scale(1)",    opacity: "0.8",  boxShadow: "0 0 0 2px rgba(239,68,68,0.6)" },
        },
        instrumentTick: {
          "0%,94%,100%": { opacity: "1" },
          "96%":         { opacity: "0.5" },
        },
        float: {
          "0%, 100%": { transform: "translateY(0)" },
          "50%":      { transform: "translateY(-4px)" },
        },
        blink: {
          "0%, 100%": { opacity: "1" },
          "50%":      { opacity: "0" },
        },
        routeEnter: {
          from: { opacity: "0", transform: "translateY(6px)" },
          to:   { opacity: "1", transform: "translateY(0)" },
        },
      },
      backgroundSize: { "200": "200% 200%" },
    },
  },
  plugins: [],
};
