"use client";

import { useState, useEffect } from "react";
import { MessageCircle } from "lucide-react";
import Chatbot from "./Chatbot";

const USER_ID = "teacher_01";

export default function ChatbotFloat() {
  const [open, setOpen] = useState(false);
  // ข้อความจากระบบที่มาตอนแชทปิดอยู่ (เช่น ผลตรวจข้อมูลก่อนจัดตาราง) -> เลขแดงบนปุ่ม จนกว่าจะเปิดอ่าน
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    // หน้าตารางส่ง event นี้มาตอนกด "สร้างตาราง" แล้วเจอปัญหาข้อมูล (การ์ดถูกเพิ่มในแชทโดย Chatbot เอง)
    const onDataCheck = () => setUnread((n) => n + 1);
    window.addEventListener("chatbot:data-check", onDataCheck);
    return () => window.removeEventListener("chatbot:data-check", onDataCheck);
  }, []);

  function openChat() {
    setOpen(true);
    setUnread(0);
  }

  return (
    <>
      <Chatbot
        open={open}
        onClose={() => setOpen(false)}
        userId={USER_ID}
      />
      {!open && (
        <button
          onClick={openChat}
          className="fixed bottom-6 right-6 w-13 h-13 rounded-full bg-orange-500 hover:bg-orange-600 active:scale-95 border-none text-white cursor-pointer shadow-lg shadow-orange-200 flex items-center justify-center z-50 transition-all"
          title={unread > 0 ? `มีข้อความใหม่ ${unread} ข้อความ` : "เปิดผู้ช่วย AI"}
          aria-label={unread > 0 ? `เปิดผู้ช่วย AI มีข้อความใหม่ ${unread} ข้อความ` : "เปิดผู้ช่วย AI"}
        >
          <MessageCircle size={20} />
          {unread > 0 && (
            <span className="absolute -top-1 -right-1 min-w-[20px] h-5 px-1 rounded-full bg-red-500 text-white text-[11px] font-semibold flex items-center justify-center ring-2 ring-white animate-bounce">
              {unread}
            </span>
          )}
        </button>
      )}
    </>
  );
}