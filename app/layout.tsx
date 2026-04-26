import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Striker14",
  description: "B2B Chatbot — Dữ liệu xuất nhập khẩu Việt Nam",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="vi">
      <body className="bg-slate-50 text-slate-900 antialiased">{children}</body>
    </html>
  );
}
