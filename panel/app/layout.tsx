import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ClinicQ panel",
  description: "ClinicQ — WhatsApp virtual token queue clinic panel",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
