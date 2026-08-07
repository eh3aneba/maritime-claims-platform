import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Maritime Claims Intelligence",
  description: "H&M Machinery Claims MVP",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
