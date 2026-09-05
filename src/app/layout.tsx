import type { Metadata, Viewport } from "next";
import "@/styles/tailwind.css";
import "@/styles/globals.scss";

export const metadata: Metadata = {
  title: "PLE Practice — Your next step, doctor.",
  description:
    "A focused space for Philippine Physicians Licensure Examination practice.",
  robots: { index: false, follow: false },
};
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#f6f5f4",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
