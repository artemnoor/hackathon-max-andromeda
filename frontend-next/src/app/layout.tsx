import type { Metadata } from "next";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";

export const metadata: Metadata = {
  title: "Andromeda · Образовательные данные",
  description:
    "Каталог образовательных программ, учебные планы, поступление, профессиональный тест и персональные рекомендации на основе открытых источников поддерживаемых университетов.",
  keywords: ["Andromeda", "учебные планы", "поступление", "профтест", "рекомендации"],
  authors: [{ name: "Andromeda" }],
  icons: {
    icon: "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='8' fill='%23c56b3f'/%3E%3Ctext x='16' y='23' font-family='Georgia,serif' font-size='20' fill='white' text-anchor='middle'%3EA%3C/text%3E%3C/svg%3E",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <body className="antialiased paper-bg min-h-screen">
        {children}
        <Toaster />
      </body>
    </html>
  );
}
