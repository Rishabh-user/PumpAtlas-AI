import type { Config } from "tailwindcss";

/**
 * Every colour resolves to a variable declared in `src/app/globals.css`, so a rebrand
 * or a theme change is an edit to that one file. Nothing in a component should reference
 * a hex value.
 *
 * Note the `<alpha-value>` placeholder on each colour: without it Tailwind cannot inject
 * an alpha and every `bg-primary/20` in the codebase silently resolves to transparent.
 */
const config: Config = {
  darkMode: ["class"],
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    container: {
      center: true,
      padding: "1.5rem",
    },
    extend: {
      colors: {
        border: "hsl(var(--border) / <alpha-value>)",
        input: "hsl(var(--input) / <alpha-value>)",
        ring: "hsl(var(--ring) / <alpha-value>)",
        background: "hsl(var(--background) / <alpha-value>)",
        foreground: "hsl(var(--foreground) / <alpha-value>)",
        primary: {
          DEFAULT: "hsl(var(--primary) / <alpha-value>)",
          foreground: "hsl(var(--primary-foreground) / <alpha-value>)",
        },
        secondary: {
          DEFAULT: "hsl(var(--secondary) / <alpha-value>)",
          foreground: "hsl(var(--secondary-foreground) / <alpha-value>)",
        },
        destructive: {
          DEFAULT: "hsl(var(--destructive) / <alpha-value>)",
          foreground: "hsl(var(--destructive-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "hsl(var(--muted) / <alpha-value>)",
          foreground: "hsl(var(--muted-foreground) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "hsl(var(--accent) / <alpha-value>)",
          foreground: "hsl(var(--accent-foreground) / <alpha-value>)",
        },
        popover: {
          DEFAULT: "hsl(var(--popover) / <alpha-value>)",
          foreground: "hsl(var(--popover-foreground) / <alpha-value>)",
        },
        card: {
          DEFAULT: "hsl(var(--card) / <alpha-value>)",
          foreground: "hsl(var(--card-foreground) / <alpha-value>)",
        },
        // Domain palettes. Semantic, and always paired with a non-colour cue.
        conf: {
          verified: "hsl(var(--conf-verified) / <alpha-value>)",
          declared: "hsl(var(--conf-declared) / <alpha-value>)",
          thirdparty: "hsl(var(--conf-thirdparty) / <alpha-value>)",
          ai: "hsl(var(--conf-ai) / <alpha-value>)",
          estimated: "hsl(var(--conf-estimated) / <alpha-value>)",
          unknown: "hsl(var(--conf-unknown) / <alpha-value>)",
        },
        sev: {
          info: "hsl(var(--sev-info) / <alpha-value>)",
          low: "hsl(var(--sev-low) / <alpha-value>)",
          medium: "hsl(var(--sev-medium) / <alpha-value>)",
          high: "hsl(var(--sev-high) / <alpha-value>)",
          critical: "hsl(var(--sev-critical) / <alpha-value>)",
        },
        grade: {
          a: "hsl(var(--grade-a) / <alpha-value>)",
          b: "hsl(var(--grade-b) / <alpha-value>)",
          c: "hsl(var(--grade-c) / <alpha-value>)",
          d: "hsl(var(--grade-d) / <alpha-value>)",
          e: "hsl(var(--grade-e) / <alpha-value>)",
        },
      },
      borderRadius: {
        lg: "var(--radius)",
        md: "calc(var(--radius) - 2px)",
        sm: "calc(var(--radius) - 3px)",
      },
      spacing: {
        rail: "var(--rail-width)",
        topbar: "var(--topbar-height)",
      },
      maxWidth: {
        content: "var(--content-max)",
      },
      height: {
        topbar: "var(--topbar-height)",
      },
      width: {
        rail: "var(--rail-width)",
      },
      fontFamily: {
        sans: ["var(--font-sans)", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: [
          "var(--font-mono)",
          "ui-monospace",
          "SFMono-Regular",
          "monospace",
        ],
      },
      fontSize: {
        // A deliberately tight scale. Dense data needs few sizes used consistently.
        "2xs": ["0.6875rem", { lineHeight: "1rem", letterSpacing: "0.01em" }],
        xs: ["0.75rem", { lineHeight: "1.125rem" }],
        sm: ["0.8125rem", { lineHeight: "1.25rem" }],
        base: ["0.875rem", { lineHeight: "1.375rem" }],
        lg: ["1rem", { lineHeight: "1.5rem" }],
        xl: ["1.25rem", { lineHeight: "1.75rem" }],
        "2xl": ["1.5rem", { lineHeight: "2rem" }],
        "3xl": ["1.875rem", { lineHeight: "2.25rem" }],
      },
      keyframes: {
        "accordion-down": {
          from: { height: "0" },
          to: { height: "var(--radix-accordion-content-height)" },
        },
        "accordion-up": {
          from: { height: "var(--radix-accordion-content-height)" },
          to: { height: "0" },
        },
        shimmer: {
          "100%": { transform: "translateX(100%)" },
        },
      },
      animation: {
        "accordion-down": "accordion-down 0.15s ease-out",
        "accordion-up": "accordion-up 0.15s ease-out",
        shimmer: "shimmer 1.4s infinite",
      },
    },
  },
  plugins: [require("tailwindcss-animate")],
};

export default config;
