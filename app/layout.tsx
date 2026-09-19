import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Literal Name Map · 名字里的世界",
  description: "The world has fewer names than you think. 在地图上发现地名的字面含义、词源与跨语言联系。",
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
