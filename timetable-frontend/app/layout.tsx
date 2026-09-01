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
        <div className="flex h-screen bg-slate-50 overflow-hidden print:h-auto print:overflow-visible">
          {/* no-print: ซ่อน sidebar เมนูซ้ายตอนสั่งพิมพ์/Export PDF ให้เหลือแค่
              เนื้อหาตาราง (ดู .no-print / .print-only ใน schedule page)
              ต้องเป็น flex ด้วย (ไม่ใช่แค่ h-full) เพราะ <aside> ข้างในพึ่ง
              align-items: stretch จาก parent ที่เป็น flex — ถ้า wrapper เป็น
              block ธรรมดา aside จะไม่ถูกยืดเต็มความสูงอัตโนมัติเหมือนตอนที่มันเป็น
              direct child ของ "flex h-screen" แบบเดิม (นี่คือสาเหตุจริงของบั๊ก) */}
          <div className="no-print flex h-full">
            <Sidebar />
          </div>
          <div className="flex-1 flex flex-col overflow-hidden print:overflow-visible">
            {children}
          </div>
        </div>
        <div className="no-print">
          <ChatbotFloat />
        </div>
      </body>
    </html>
  );
}