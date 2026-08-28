import type { Metadata } from "next";
import { Prompt } from "next/font/google";
import "./globals.css";
import Sidebar from "../components/Sidebar";
import ChatbotFloat from "../components/ChatbotFloat";

const prompt = Prompt({
  subsets: ["thai", "latin"],
  weight: ["300", "400", "500", "700"],
});

export const metadata: Metadata = {
  title: "ระบบจัดตารางการเรียนการสอน",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="th" className="h-full antialiased">
      <body className={`${prompt.className} h-full`}>
        <div className="flex h-screen bg-slate-50 overflow-hidden">
          <Sidebar />
          <div className="flex-1 flex flex-col overflow-hidden">
            {children}
          </div>
        </div>
        <ChatbotFloat />
      </body>
    </html>
  );
}
