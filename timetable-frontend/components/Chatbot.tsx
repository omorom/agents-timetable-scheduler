"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { Bot, Send, X, User, AlertTriangle, ArrowRight, Sparkles, Wrench, SkipForward } from "lucide-react";
import { ChatMessage, API_BASE } from "./types";

// ── ผลตรวจข้อมูลก่อนจัดตาราง (GET /check-data — DataGatherAgent, ดู data_check_service.py ฝั่ง backend) ──
interface DataIssue {
  id: string;
  kind: string;
  severity: "blocking" | "warning";
  title: string;        // หัวข้อสั้น เช่น "ผศ.ดร.ธนะธร พ่อค้า ไม่มีเวลาว่าง"
  facts: string;        // ตัวเลขประกอบ เช่น "ต้องสอน 5 คาบ ว่าง 0 คาบ"
  suggestion: string;   // ทางแก้หลัก
  alt: string;          // ทางแก้รอง / ข้อมูลเสริม (พับเก็บไว้)
  subjects: string[];   // วิชาที่จะได้รับผลกระทบ
  detail: string;       // ประโยคเต็ม (ใช้เมื่อไม่มี title)
  fix_page: "teachers" | "rooms" | "subjects" | string;
}
interface DataOption {
  id: string;
  text: string;
  reason?: string;
}
interface DataCheck {
  ok: boolean;
  message: string;
  blocking: DataIssue[];
  warning: DataIssue[];
  summary?: string;      // DataReviewAgent (LLM): ข้อความถึงผู้ใช้ — ว่างถ้า LLM ไม่ได้ตอบ (ใช้ message แทน)
  decision?: "fix_first" | "ok_to_continue" | null;   // DataReviewAgent ตัดสิน: ควรแก้ก่อน / จัดต่อได้
  // ทางเลือก 2-3 ทาง เรียงจากที่แนะนำที่สุด
  // text = ทางแก้ที่ Python คำนวณ (ตัวเลข/เวลาแม่นยำ), reason = เหตุผลที่ AI เขียน (ว่าง = ชุดสำรองจาก Python)
  options?: DataOption[];
  session_id?: string;   // ส่งกลับไปตอน /generate เพื่อใช้ผลตรวจนี้ต่อ ไม่ตรวจซ้ำ
}

// ลิงก์ "ไปแก้" ในการ์ดพาไปหน้าไหน
// ข้อมูลทุกอย่าง (อาจารย์ / ห้องเรียน / รายวิชา) อยู่หน้า "ข้อมูลในระบบ" /data ที่เดียว
// label ยังแยกตามเรื่อง ผู้ใช้จะได้รู้ว่าเข้าไปแล้วต้องแก้ส่วนไหน
const FIX_ROUTES: Record<string, { href: string; label: string }> = {
  teachers: { href: "/data", label: "ไปแก้ข้อมูลอาจารย์" },
  rooms: { href: "/data", label: "ไปแก้ข้อมูลห้องเรียน" },
  subjects: { href: "/data", label: "ไปแก้ข้อมูลรายวิชา" },
};

// ข้อความในแชท + การ์ดผลตรวจข้อมูล (ถ้ามี)
type ChatItem = ChatMessage & { card?: DataCheck; cardDone?: boolean };

function nowTime() {
  return new Date().toLocaleTimeString("th-TH", { hour: "2-digit", minute: "2-digit" });
}

// กล่องแดง = "ปัญหาคืออะไร" (Python)
// hideSuggestion: กล่อง AI แสดงทางเลือกให้แล้ว -> ไม่ต้องบอกทางแก้ซ้ำในกล่องนี้
//                 (AI ล่ม/ไม่ตอบ -> แสดงทางแก้ตามเดิม ผู้ใช้ไม่ตกหล่น)
function IssueBox({ issue, hideLink, hideSuggestion }: { issue: DataIssue; hideLink?: boolean; hideSuggestion?: boolean }) {
  const route = FIX_ROUTES[issue.fix_page] ?? FIX_ROUTES.subjects;
  const showAlt = !!issue.alt && !hideSuggestion;
  const hasMore = issue.subjects.length > 0 || showAlt;
  return (
    <div className="rounded-xl border border-red-100 bg-red-50/60 px-3 py-2.5">
      <div className="flex gap-1.5 text-[12.5px] font-semibold text-red-700 leading-snug">
        <AlertTriangle size={13} className="mt-0.5 shrink-0" />
        <span>{issue.title || issue.detail}</span>
      </div>
      {issue.facts && <div className="pl-[19px] text-[11.5px] text-gray-500 mt-0.5">{issue.facts}</div>}
      {issue.suggestion && !hideSuggestion && (
        <div className="pl-[19px] mt-1.5 text-[12px] text-gray-700 leading-snug">
          <span className="font-semibold text-gray-800">แนะนำ: </span>{issue.suggestion}
        </div>
      )}
      {hasMore && (
        <details className="pl-[19px] mt-1.5 text-[11.5px] text-gray-500">
          <summary className="cursor-pointer select-none hover:text-gray-700">
            {issue.subjects.length > 0 ? `ดูวิชาที่กระทบ (${issue.subjects.length})` : "ดูเพิ่ม"}
          </summary>
          <div className="mt-1 flex flex-col gap-1">
            {issue.subjects.length > 0 && <div>{issue.subjects.join(", ")}</div>}
            {showAlt && <div>ทางเลือกอื่น: {issue.alt.replace(/^หรือ\s*/, "")}</div>}
          </div>
        </details>
      )}
      {!hideLink && (
        <Link
          href={route.href}
          className="pl-[19px] mt-1.5 inline-flex items-center gap-1 text-[11.5px] font-semibold text-orange-600 hover:text-orange-700"
        >
          {route.label} <ArrowRight size={12} />
        </Link>
      )}
    </div>
  );
}

// ป้ายเล็กชิดขวาบนปุ่มที่ AI แนะนำ (สีเปลี่ยนตามพื้นปุ่ม)
function AiPick({ onPrimary }: { onPrimary: boolean }) {
  return (
    <span className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2 py-0.5 text-[10px] font-semibold
      ${onPrimary ? "bg-white/20 text-white ring-1 ring-white/30" : "bg-violet-50 text-violet-600 ring-1 ring-violet-200"}`}>
      <Sparkles size={9} /> AI แนะนำ
    </span>
  );
}

// ปุ่มเต็มความกว้าง ซ้อนกัน: ไอคอน + ข้อความทางซ้าย, ป้าย AI หรือลูกศรทางขวา
const BTN_BASE =
  "group flex w-full items-center justify-between gap-2 rounded-xl px-3.5 py-2.5 text-[12.5px] no-underline cursor-pointer transition-all";
const BTN_PRIMARY =
  `${BTN_BASE} border border-orange-500 bg-orange-500 font-semibold text-white shadow-sm shadow-orange-200 hover:bg-orange-600 hover:border-orange-600 active:scale-[0.99]`;
const BTN_SECONDARY =
  `${BTN_BASE} border border-gray-200 bg-white font-medium text-gray-600 hover:border-gray-300 hover:bg-gray-50 active:scale-[0.99]`;

function DataCheckCard({ card, done, onContinue }: { card: DataCheck; done?: boolean; onContinue: () => void }) {
  // ปุ่มเรียงแบบเดียวกันทุกครั้ง: [ไปแก้ข้อมูล] [จัดต่อเลย]
  // AI ตัดสินแค่ว่าปุ่มไหนเป็นปุ่มหลัก (สีส้ม + ป้าย "AI แนะนำ")
  //   "fix_first"      -> ปุ่ม "ไปแก้" เป็นปุ่มหลัก
  //   "ok_to_continue" -> ปุ่ม "จัดต่อเลย" เป็นปุ่มหลัก
  //   ไม่มีคำตัดสิน (AI ไม่ตอบ / ตอบไม่ทัน) -> ปุ่ม "ไปแก้" เป็นปุ่มหลัก เพราะมีปัญหาที่จัดไม่ได้แน่ แต่ไม่มีป้าย AI
  const decided = !!card.summary && (card.decision === "fix_first" || card.decision === "ok_to_continue");
  const preferContinue = decided && card.decision === "ok_to_continue";
  const firstRoute = card.blocking.length > 0
    ? (FIX_ROUTES[card.blocking[0].fix_page] ?? FIX_ROUTES.subjects)
    : null;
  // มีปัญหาเรื่องเดียว ปุ่ม "ไปแก้" ด้านล่างพาไปที่เดียวกันอยู่แล้ว -> ซ่อนลิงก์ในกล่อง ไม่ให้ซ้ำ
  const hideLink = card.blocking.length === 1;
  // AI เสนอทางเลือกแล้ว -> กล่องแดงบอกแค่ "ปัญหาคืออะไร" ไม่ต้องบอกทางแก้ซ้ำ
  const hasAiOptions = !!card.summary && (card.options?.length ?? 0) > 1;

  // ลำดับการอ่าน: ปัญหาคืออะไร (Python) -> ควรทำอะไร (AI) -> ปุ่ม
  return (
    <div className="mt-2.5 flex flex-col gap-2">
      {card.blocking.map((issue) => (
        <IssueBox key={issue.id} issue={issue} hideLink={hideLink || hasAiOptions} hideSuggestion={hasAiOptions} />
      ))}

      {/* คำวิเคราะห์ของ DataReviewAgent — แยกกล่องให้เห็นชัดว่าเป็น AI */}
      {card.summary && (
        <div className="rounded-xl border border-violet-200 bg-linear-to-br from-violet-50 to-orange-50 px-3 py-2.5">
          <div className="mb-1 flex items-center gap-1.5 text-[11px] font-semibold text-violet-600">
            <span className="flex h-4 w-4 items-center justify-center rounded-full bg-violet-500 text-white">
              <Sparkles size={9} />
            </span>
            AI วิเคราะห์ให้
          </div>
          <p className="m-0 text-[12.5px] leading-relaxed text-gray-800 [text-wrap:pretty]">{card.summary}</p>
          {/* ทางเลือกที่ AI เสนอ — ข้อแรก = ทางที่แนะนำที่สุด */}
          {card.options && card.options.length > 1 && (
            <div className="mt-2 border-t border-violet-100 pt-2">
              <div className="mb-1 text-[11px] font-semibold text-violet-600">ทางเลือกที่ทำได้</div>
              {/* ใช้ div แทน ol: เลขในวงกลมคือเลขข้อ ไม่ให้เบราว์เซอร์ใส่เลขซ้ำ */}
              <div className="flex flex-col gap-1.5">
                {card.options.map((o, idx) => {
                  // รองรับผลแบบเก่า (string ล้วน) เผื่อ backend ยังไม่อัปเดต
                  const opt: DataOption = typeof o === "string" ? { id: String(idx), text: o } : o;
                  return (
                    <div key={opt.id} className="flex gap-1.5 text-[12px] leading-snug">
                      <span className={`mt-px flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold
                        ${idx === 0 ? "bg-violet-500 text-white" : "bg-violet-100 text-violet-600"}`}>
                        {idx + 1}
                      </span>
                      <div className="flex flex-col gap-0.5">
                        <span className="font-medium text-gray-800">
                          {opt.text.replace(/^หรือ\s*/, "")}
                          {idx === 0 && <span className="ml-1.5 whitespace-nowrap rounded-full bg-violet-100 px-1.5 py-px text-[10px] font-semibold text-violet-600">แนะนำ</span>}
                        </span>
                        {opt.reason && <span className="text-[11.5px] text-gray-500">{opt.reason}</span>}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {card.warning.length > 0 && (
        <details className="rounded-xl border border-amber-100 bg-amber-50/60 px-3 py-2 text-[12px] text-gray-700">
          <summary className="cursor-pointer select-none font-medium text-amber-700">ควรระวังอีก {card.warning.length} เรื่อง</summary>
          <ul className="mt-1.5 flex flex-col gap-1.5 pl-1">
            {card.warning.map((w) => (
              <li key={w.id}>
                <span className="font-medium">{w.title || w.detail}</span>
                {w.facts && <span className="text-gray-500"> · {w.facts}</span>}
                {w.suggestion && <div className="text-[11px] text-gray-500">แนะนำ: {w.suggestion}</div>}
              </li>
            ))}
          </ul>
        </details>
      )}

      {done ? (
        <div className="text-[11.5px] text-gray-400">เริ่มจัดตารางแล้ว วิชาที่ติดปัญหาจะอยู่ในรายการวิชาที่จัดไม่ได้</div>
      ) : (
        <div className="mt-0.5 flex flex-col gap-1.5">
          {firstRoute && (() => {
            const primary = !preferContinue;
            return (
              <Link href={firstRoute.href} className={primary ? BTN_PRIMARY : BTN_SECONDARY}>
                <span className="flex items-center gap-2">
                  <Wrench size={13} className={primary ? "opacity-90" : "text-gray-400"} />
                  {firstRoute.label}
                </span>
                {decided && primary
                  ? <AiPick onPrimary />
                  : <ArrowRight size={13} className="shrink-0 transition-transform group-hover:translate-x-0.5" />}
              </Link>
            );
          })()}
          {(() => {
            const primary = preferContinue || !firstRoute;
            return (
              <button onClick={onContinue} className={primary ? BTN_PRIMARY : BTN_SECONDARY}>
                <span className="flex items-center gap-2">
                  <SkipForward size={13} className={primary ? "opacity-90" : "text-gray-400"} />
                  จัดต่อเลย ข้ามวิชาเหล่านี้
                </span>
                {preferContinue && <AiPick onPrimary={primary} />}
              </button>
            );
          })()}
        </div>
      )}
    </div>
  );
}

const QUICK_QUESTIONS = [
  "อาจารย์ ลิมปพัทธ์ ไม่ว่างช่วงไหนบ้าง",
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
  const [messages, setMessages] = useState<ChatItem[]>([{
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

  // หน้าตารางกด "สร้างตาราง" แล้วเจอปัญหาข้อมูล -> ส่งผลตรวจมาให้แสดงเป็นการ์ดในแชท
  // (ตัวที่เปิดหน้าต่างแชทฟัง event เดียวกันนี้แล้วสั่งเปิดเอง)
  useEffect(() => {
    function onDataCheck(e: Event) {
      const card = (e as CustomEvent<DataCheck>).detail;
      if (!card) return;
      // ข้อความแชทใช้คำของ DataReviewAgent (AI) ถ้ามี ไม่งั้นใช้หัวข้อสรุปจาก Python
      setMessages(prev => [...prev, { role: "assistant", text: card.summary || card.message, time: nowTime(), card }]);
    }
    window.addEventListener("chatbot:data-check", onDataCheck);
    return () => window.removeEventListener("chatbot:data-check", onDataCheck);
  }, []);

  function continueGenerate(index: number) {
    const sessionId = messages[index]?.card?.session_id;
    setMessages(prev => prev.map((m, i) => (i === index ? { ...m, cardDone: true } : m)));
    window.dispatchEvent(new CustomEvent("chatbot:continue-generate", { detail: { session_id: sessionId } }));
  }

  // ปัญหาจากการ์ดผลตรวจล่าสุด ส่งไปให้แชทบอทรู้ว่าผู้ใช้กำลังพูดถึงอะไร
  // (ไม่งั้นคำถามลอยๆ อย่าง "เปลี่ยนห้องดีไหม" บอทไม่รู้บริบท แล้วตีความว่านอกเรื่อง)
  function lastCardContext(): string {
    const card = [...messages].reverse().find(m => m.card && !m.cardDone)?.card;
    if (!card || card.blocking.length === 0) return "";
    // ใส่ให้ครบเท่าที่ผู้ใช้เห็นบนการ์ด (รวมวิชาที่กระทบ + ทางแก้รอง) บอทจะได้ไม่ต้องถามกลับ
    return card.blocking
      .map(i => [
        `- ${i.title || i.detail}${i.facts ? ` (${i.facts})` : ""}`,
        i.subjects.length > 0 ? `  วิชาที่กระทบ: ${i.subjects.join(", ")}` : "",
        i.suggestion ? `  แนะนำ: ${i.suggestion}` : "",
        i.alt ? `  ทางเลือกอื่น: ${i.alt}` : "",
      ].filter(Boolean).join("\n"))
      .join("\n");
  }

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
        body: JSON.stringify({ message: text, user_id: userId, context: lastCardContext() }),
      });
      const data = await res.json();
      // ตัดช่องว่าง/บรรทัดว่างหัวท้าย และยุบบรรทัดว่างที่ซ้อนกันเกิน 1 บรรทัด
      // (LLM ชอบส่ง \n\n\n มา ทำให้ข้อความดูห่างเกินไปในกล่องแคบ)
      const reply = String(data.reply || "ขออภัย ไม่สามารถตอบได้ในขณะนี้")
        .trim()
        .replace(/\n{3,}/g, "\n\n");
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
    <div className="fixed bottom-6 right-6 w-[380px] h-[560px] bg-white rounded-2xl shadow-2xl flex flex-col z-50 border border-gray-100 overflow-hidden animate-slide-right">

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

            {/* กล่องข้อความของ bot กว้างกว่าของผู้ใช้ (88% vs 78%) เพราะคำตอบยาวกว่า
                ภาษาไทยไม่มีเว้นวรรค กล่องแคบจะตัดบรรทัดกลางวลีบ่อย */}
            <div className={`flex flex-col gap-1 ${msg.role === "user" ? "max-w-[78%] items-end" : "max-w-[88%] items-start"}`}>
              <div className={`px-3.5 py-2.5 text-[13px] leading-relaxed shadow-sm
                ${msg.role === "user"
                  ? "bg-orange-500 text-white rounded-2xl rounded-br-sm"
                  : "bg-white text-gray-800 border border-gray-100 rounded-2xl rounded-bl-sm"}`}
              >
                {/* text-wrap: pretty ให้เบราว์เซอร์เกลี่ยการตัดบรรทัด ไม่เหลือคำเดียวค้างบรรทัดท้าย */}
                <p className="whitespace-pre-wrap break-words [text-wrap:pretty] m-0">
                  {msg.card?.summary
                    ? `ตรวจข้อมูลก่อนจัดตารางแล้ว พบปัญหา ${msg.card.blocking.length} เรื่อง`
                    : msg.text}
                </p>
                {msg.card && (
                  <DataCheckCard card={msg.card} done={msg.cardDone} onContinue={() => continueGenerate(i)} />
                )}
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