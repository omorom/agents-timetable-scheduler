"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  CalendarDays, LayoutGrid, BookOpen, Database, ChevronRight, ChevronLeft,
} from "lucide-react";

const NAV = [
  { href: "/",         icon: LayoutGrid, label: "จัดตาราง" },
  { href: "/subjects", icon: BookOpen,   label: "จัดการรายวิชา" },
  { href: "/data",     icon: Database,   label: "ข้อมูลในระบบ" },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);

  return (
    <aside
      className={`bg-white border-r border-gray-100 flex flex-col shrink-0 shadow-sm z-20 transition-all duration-200
        ${collapsed ? "w-16" : "w-60"}`}
    >
      {/* Branding + ปุ่มพับ/ขยาย อยู่แถวเดียวกัน เรียบๆ ไม่มีเงาลอย เหมือนแอปทั่วไป */}
      <div className={`border-b border-gray-100 ${collapsed ? "px-3 py-5" : "px-5 py-5"}`}>
        <div className={`flex items-center ${collapsed ? "flex-col gap-2" : "justify-between"}`}>
          <div
            className={`bg-linear-to-br from-orange-400 to-orange-600 rounded-xl flex items-center justify-center text-white shrink-0
              ${collapsed ? "w-9 h-9" : "w-10 h-10"}`}
          >
            <CalendarDays size={collapsed ? 17 : 19} />
          </div>
          <button
            onClick={() => setCollapsed((v) => !v)}
            title={collapsed ? "ขยายเมนู" : "พับเมนู"}
            className="w-6 h-6 rounded-md flex items-center justify-center text-gray-300 hover:text-gray-500 hover:bg-gray-50 transition-colors cursor-pointer shrink-0"
          >
            {collapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>
        {!collapsed && (
          <>
            <div className="text-[14px] font-bold text-gray-900 leading-snug mt-3">
              ระบบจัดตารางการเรียนการสอน
            </div>
            <div className="text-[10px] text-gray-400 mt-1.5 leading-relaxed">
              ภาควิชาวิทยาการคอมพิวเตอร์<br />และเทคโนโลยีสารสนเทศ
            </div>
          </>
        )}
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {!collapsed && (
          <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider px-3 mb-2">
            เมนูหลัก
          </p>
        )}
        {NAV.map(({ href, icon: Icon, label }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              title={collapsed ? label : undefined}
              className={`flex items-center gap-3 rounded-xl text-sm font-medium transition-all no-underline
                ${collapsed ? "px-0 py-2.5 justify-center" : "px-3 py-2.5"}
                ${active
                  ? "bg-orange-50 text-orange-600"
                  : "text-gray-500 hover:bg-gray-50 hover:text-gray-800"}`}
            >
              <Icon size={16} className={active ? "text-orange-500" : "text-gray-400"} />
              {!collapsed && (
                <>
                  <span className="flex-1">{label}</span>
                  {active && <ChevronRight size={14} className="text-orange-400" />}
                </>
              )}
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