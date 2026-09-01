import type { Metadata } from "next";

import { LocaleProvider } from "@/components/locale-provider";

import "./globals.css";

export const metadata: Metadata = {
  title: "Maritime Claims Intelligence",
  description: "Evidence-first marine claims management for H&M machinery claims",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" dir="ltr" suppressHydrationWarning>
      <body>
        <LocaleProvider>{children}</LocaleProvider>
      </body>
    </html>
  );
}
