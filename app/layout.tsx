import type { Metadata } from "next";
import "@fontsource-variable/roboto/wght.css";
import "./globals.css";

export const metadata: Metadata = {
  title: "Place, Literally",
  description: "Explore what place names mean—and where meanings meet. 在地图上探索地名的字面含义与跨语言联系。",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="antialiased">{children}</body>
    </html>
  );
}
