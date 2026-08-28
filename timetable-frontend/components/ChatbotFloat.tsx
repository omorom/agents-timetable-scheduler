"use client";

import { useState } from "react";
import { MessageCircle } from "lucide-react";
import Chatbot from "./Chatbot";

const USER_ID = "teacher_01";

export default function ChatbotFloat() {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Chatbot
        open={open}
        onClose={() => setOpen(false)}
        userId={USER_ID}
      />
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 w-13 h-13 rounded-full bg-orange-500 hover:bg-orange-600 active:scale-95 border-none text-white cursor-pointer shadow-lg shadow-orange-200 flex items-center justify-center z-50 transition-all"
          title="เปิดผู้ช่วย AI"
        >
          <MessageCircle size={20} />
        </button>
      )}
    </>
  );
}
