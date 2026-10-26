import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "EvoDesign Renderer",
  description: "Local rendering service for editable EvoDesign diagrams.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
