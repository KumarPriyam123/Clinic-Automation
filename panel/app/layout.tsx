import type { Metadata, Viewport } from "next";
import { Noto_Sans } from "next/font/google";
import "./globals.css";
import { SwRegister } from "./components/SwRegister";
import { ProdBackendWarning } from "./components/ProdBackendWarning";
import { LocaleProvider } from "./lib/locale";

const noto = Noto_Sans({
  subsets: ["latin", "devanagari"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
  variable: "--font-noto",
});

export const metadata: Metadata = {
  title: "ClinicQ",
  description: "ClinicQ — WhatsApp virtual token queue clinic panel",
  manifest: "/manifest.webmanifest",
  appleWebApp: { capable: true, statusBarStyle: "default", title: "ClinicQ" },
  // Emits <meta name="google" content="notranslate">. Next 14's app router owns
  // <head>, so this is the supported way to write the tag. Together with
  // translate="no" and class="notranslate" below it stops Chrome from offering
  // to translate the panel — machine translation turned the Hindi closed-STATE
  // label into "Close", an imperative, sitting next to the control that closes
  // a session. The panel ships its own translations (lib/i18n.ts) instead.
  other: { google: "notranslate" },
};

export const viewport: Viewport = {
  themeColor: "#0f766e",
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  // lang="hi" is the SSR default; LocaleProvider rewrites it once the real
  // locale is known (manual override → clinic.language).
  return (
    <html lang="hi" translate="no" className={`${noto.variable} notranslate`}>
      <body className="font-sans antialiased">
        <ProdBackendWarning />
        <LocaleProvider>{children}</LocaleProvider>
        <SwRegister />
      </body>
    </html>
  );
}
