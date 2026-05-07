import "@/styles/globals.css";

import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "AI ERP Platform",
  description: "AI-powered ERP generation and JD Edwards copiloting"
};

export default function RootLayout({
  children
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
