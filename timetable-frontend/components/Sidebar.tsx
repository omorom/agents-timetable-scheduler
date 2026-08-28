"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CalendarDays, LayoutGrid, BookOpen, Database, ChevronRight,
} from "lucide-react";

const NAV = [
  { href: "/",         icon: LayoutGrid, label: "จัดตาราง" },
  { href: "/subjects", icon: BookOpen,   label: "จัดการรายวิชา" },
  { href: "/data",     icon: Database,   label: "ข้อมูลในระบบ" },
];

export default function Sidebar() {
  const pathname = usePathname();

  return (
    <aside className="w-60 bg-white border-r border-gray-100 flex flex-col shrink-0 shadow-sm z-20">
      {/* Branding */}
      <div className="px-5 py-5 border-b border-gray-100">
        <div className="w-10 h-10 bg-linear-to-br from-orange-400 to-orange-600 rounded-xl flex items-center justify-center text-white shadow shadow-orange-200 mb-3">
          <CalendarDays size={19} />
        </div>
        <div className="text-[14px] font-bold text-gray-900 leading-snug">
          ระบบจัดตารางการเรียนการสอน
        </div>
        <div className="text-[10px] text-gray-400 mt-1.5 leading-relaxed">
          ภาควิชาวิทยาการคอมพิวเตอร์<br />และเทคโนโลยีสารสนเทศ
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-3 mb-2">
          เมนูหลัก
        </p>
        {NAV.map(({ href, icon: Icon, label }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all no-underline
                ${active
                  ? "bg-orange-50 text-orange-600"
                  : "text-gray-500 hover:bg-gray-50 hover:text-gray-800"}`}
            >
              <Icon size={16} className={active ? "text-orange-500" : "text-gray-400"} />
              <span className="flex-1">{label}</span>
              {active && <ChevronRight size={14} className="text-orange-400" />}
            </Link>
          );
        })}
      </nav>

      {/* Footer */}
      {/* <div className="px-5 py-4 border-t border-gray-100">
        <p className="text-[10px] text-gray-300 leading-relaxed">
          Senior Project · 2567<br />v1.0.0
        </p>
      </div> */}
    </aside>
  );
}
