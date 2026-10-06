import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import { ThemeProvider } from "next-themes";

import "./globals.css";

/**
 * Inter for the interface, JetBrains Mono for every figure and identifier.
 *
 * Both load as CSS variables the Tailwind config points at, so a font that fails to
 * fetch degrades to the platform UI stack rather than to the browser's serif default.
 */
const sans = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});

const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  weight: ["400", "500", "700"],
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: { default: "PumpAtlas AI", template: "%s · PumpAtlas AI" },
  description:
    "Oil & Gas pump intelligence: product, vendor and procurement data with full " +
    "provenance. By Targeticon.",
  applicationName: "PumpAtlas AI",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#0d1219" },
    { media: "(prefers-color-scheme: light)", color: "#f7f9fb" },
  ],
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en-GB"
      suppressHydrationWarning
      className={sans.variable + " " + mono.variable}
    >
      <body>
        {/* Dark is the working default; the choice is remembered per browser. */}
        <ThemeProvider
          attribute="class"
          defaultTheme="dark"
          enableSystem
          disableTransitionOnChange
        >
          {children}
        </ThemeProvider>
      </body>
    </html>
  );
}
