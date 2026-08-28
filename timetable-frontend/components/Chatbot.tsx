"use client";

import { useState, useEffect, useRef } from "react";
import { Bot, Send, X, User } from "lucide-react";
import { ChatMessage, API_BASE } from "./types";

const QUICK_QUESTIONS = [
  "อาจารย์ ลิมปพัทธ์ ไม่ว่างข่วงไหนบ้าง",
  "ห้องไหนว่างช่วงบ่าย?",
  "มีนิสิตชั้นปีที่ 3 จำนวนกี่คน",
  "จำนวนรายวิชาที่เปิดสอนในภาคเรียนนี้",
];

interface Props {
  open: boolean;
  onClose: () => void;
  userId: string;
  onScheduleGenerated?: () => void;
}

export default function Chatbot({ open, onClose, userId, onScheduleGenerated }: Props) {
  const [messages, setMessages] = useState<ChatMessage[]>([{
    role: "assistant",
    text: "สวัสดีค่ะ ดิฉันคือผู้ช่วย AI สำหรับระบบจัดตารางเรียน\nพิมพ์คำถามหรือเลือกหัวข้อด้านล่างได้เลยค่ะ",
    time: new Date().toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" }),
  }]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 150);
  }, [open]);

  async function sendMessage(text: string) {
    if (!text.trim() || loading) return;
    const time = new Date().toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" });
    setMessages(prev => [...prev, { role: "user", text, time }]);
    setInput("");
    setLoading(true);
    try {
      const res = await fetch(`${API_BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, user_id: userId }),
      });
      const data = await res.json();
      const reply = data.reply || "ขออภัย ไม่สามารถตอบได้ในขณะนี้";
      setMessages(prev => [...prev, {
        role: "assistant",
        text: reply,
        time: new Date().toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" }),
      }]);
      if (reply.includes("จัดตาราง") || reply.includes("schedule_table")) {
        onScheduleGenerated?.();
      }
    } catch {
      setMessages(prev => [...prev, {
        role: "assistant",
        text: "เกิดข้อผิดพลาด กรุณาลองใหม่อีกครั้ง",
        time,
      }]);
    } finally {
      setLoading(false);
    }
  }

  if (!open) return null;

  return (
    <div className="fixed bottom-6 right-6 w-[360px] h-[540px] bg-white rounded-2xl shadow-2xl flex flex-col z-50 border border-gray-100 overflow-hidden animate-slide-right">

      {/* Header */}
      <div className="bg-linear-to-r from-orange-500 to-orange-400 px-4 py-3 flex items-center justify-between shrink-0">
        <div className="flex items-center gap-2.5">
          <div className="w-8 h-8 rounded-full bg-white/20 border border-white/30 flex items-center justify-center text-white">
            <Bot size={16} />
          </div>
          <div>
            <div className="text-white font-semibold text-[13px] leading-tight">ผู้ช่วย AI</div>
            <div className="flex items-center gap-1 mt-0.5">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-300 animate-pulse inline-block" />
              <span className="text-white/70 text-[10px]">พร้อมตอบคำถาม</span>
            </div>
          </div>
        </div>
        <button
          onClick={onClose}
          className="w-7 h-7 rounded-full bg-white/15 hover:bg-white/30 flex items-center justify-center text-white cursor-pointer transition-colors border-none"
        >
          <X size={15} />
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3 bg-slate-50/50">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`flex items-end gap-2 animate-fade-up ${msg.role === "user" ? "flex-row-reverse" : "flex-row"}`}
          >
            <div className={`w-6 h-6 rounded-full flex items-center justify-center shrink-0 mb-1
              ${msg.role === "user"
                ? "bg-orange-100 text-orange-500"
                : "bg-white border border-gray-200 text-gray-400"}`}
            >
              {msg.role === "user" ? <User size={12} /> : <Bot size={12} />}
            </div>

            <div className={`max-w-[78%] flex flex-col gap-1 ${msg.role === "user" ? "items-end" : "items-start"}`}>
              <div className={`px-3.5 py-2.5 text-[13px] leading-relaxed shadow-sm
                ${msg.role === "user"
                  ? "bg-orange-500 text-white rounded-2xl rounded-br-sm"
                  : "bg-white text-gray-800 border border-gray-100 rounded-2xl rounded-bl-sm"}`}
              >
                <p className="whitespace-pre-wrap m-0">{msg.text}</p>
              </div>
              <span className="text-[10px] text-gray-400 px-1">{msg.time}</span>
            </div>
          </div>
        ))}

        {/* Typing indicator */}
        {loading && (
          <div className="flex items-end gap-2 animate-fade-up">
            <div className="w-6 h-6 rounded-full bg-white border border-gray-200 text-gray-400 flex items-center justify-center shrink-0">
              <Bot size={12} />
            </div>
            <div className="bg-white border border-gray-100 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm flex items-center gap-1.5">
              {[0, 1, 2].map(i => (
                <span
                  key={i}
                  className="w-2 h-2 rounded-full bg-orange-300 animate-bounce inline-block"
                  style={{ animationDelay: `${i * 0.18}s` }}
                />
              ))}
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Quick questions */}
      <div className="px-4 py-2.5 border-t border-gray-100 bg-white shrink-0">
        <div className="text-[10px] text-gray-400 font-semibold mb-1.5 uppercase tracking-wider">คำถามด่วน</div>
        <div className="flex flex-wrap gap-1.5">
          {QUICK_QUESTIONS.map(q => (
            <button
              key={q}
              onClick={() => sendMessage(q)}
              disabled={loading}
              className="bg-orange-50 hover:bg-orange-100 active:bg-orange-200 border border-orange-200 text-orange-700 text-[11px] rounded-full px-2.5 py-1 cursor-pointer transition-colors disabled:opacity-40 disabled:cursor-default whitespace-nowrap font-medium"
            >
              {q}
            </button>
          ))}
        </div>
      </div>

      {/* Input */}
      <div className="px-4 py-3 border-t border-gray-100 bg-white flex gap-2 items-center shrink-0">
        <input
          ref={inputRef}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === "Enter" && !e.shiftKey && sendMessage(input)}
          placeholder="พิมพ์คำถามของคุณ..."
          disabled={loading}
          className="flex-1 border border-gray-200 rounded-full px-4 py-2 text-[13px] outline-none bg-gray-50 focus:bg-white focus:border-orange-300 transition-colors placeholder:text-gray-400 disabled:opacity-50"
        />
        <button
          onClick={() => sendMessage(input)}
          disabled={loading || !input.trim()}
          className={`w-9 h-9 rounded-full border-none flex items-center justify-center text-white shrink-0 transition-all
            ${input.trim() && !loading
              ? "bg-orange-500 hover:bg-orange-600 active:scale-95 cursor-pointer shadow-sm shadow-orange-200"
              : "bg-gray-200 cursor-default"}`}
        >
          <Send size={14} />
        </button>
      </div>
    </div>
  );
}