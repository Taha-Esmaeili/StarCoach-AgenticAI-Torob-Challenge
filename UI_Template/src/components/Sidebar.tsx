import React from 'react';
import {
  Plus,
  MessageSquare,
  CheckCircle2,
  Store,
  CreditCard,
  Clock,
  X,
  SlidersHorizontal,
  Trash2,
} from 'lucide-react';
import { TorobLogo } from './TorobLogo';
import type { ActiveWeightSlotDto } from '../api/client';

export interface SidebarSessionItem {
  sessionId: string;
  title: string;
  updatedAtLabel?: string;
}

interface SidebarProps {
  isOpen: boolean;
  onClose: () => void;
  onNewChat: () => void;
  sessions: SidebarSessionItem[];
  activeSessionId: string;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
  filterOpenOnly: boolean;
  setFilterOpenOnly: (val: boolean) => void;
  filterTorobPay: boolean;
  setFilterTorobPay: (val: boolean) => void;
  filterInstallment: boolean;
  setFilterInstallment: (val: boolean) => void;
  activeWeights?: ActiveWeightSlotDto[];
  onWeightChange?: (key: string, val: number) => void;
}

export const Sidebar: React.FC<SidebarProps> = ({
  isOpen,
  onClose,
  onNewChat,
  sessions,
  activeSessionId,
  onSelectSession,
  onDeleteSession,
  filterOpenOnly,
  setFilterOpenOnly,
  filterTorobPay,
  setFilterTorobPay,
  filterInstallment,
  setFilterInstallment,
  activeWeights,
  onWeightChange,
}) => {
  const todayFa = new Date().toLocaleDateString('fa-IR');

  return (
    <>
      {/* Backdrop for mobile */}
      {isOpen && (
        <div
          onClick={onClose}
          className="fixed inset-0 z-40 bg-black/80 backdrop-blur-xs md:hidden"
        />
      )}

      {/* Slide-out Sidebar from the right */}
      <aside
        className={`fixed md:relative inset-y-0 right-0 z-50 h-full bg-[#0d0d12] border-l border-[#1c1c24] flex flex-col justify-between transition-all duration-300 ease-in-out ${
          isOpen
            ? 'w-72 translate-x-0 opacity-100'
            : 'w-0 -translate-x-full md:translate-x-0 md:w-0 overflow-hidden opacity-0 pointer-events-none border-none'
        }`}
      >
        <div className="w-72 flex flex-col h-full justify-between">
          {/* Top: New chat button & close */}
          <div className="p-3.5 border-b border-[#1c1c24] flex items-center gap-2">
            <button
              onClick={() => {
                onNewChat();
                if (window.innerWidth < 768) onClose();
              }}
              className="flex-1 flex items-center justify-center gap-2 py-2.5 px-4 rounded-xl bg-[#15151c] hover:bg-[#1e1e27] border border-[#23232c] hover:border-[#e9325a]/50 text-neutral-200 text-xs font-bold transition-all shadow-sm group"
            >
              <Plus className="w-4 h-4 text-[#e9325a] group-hover:scale-110 transition-transform" />
              <span>گفت‌وگوی جدید</span>
            </button>

            <button
              onClick={onClose}
              className="p-2 rounded-xl text-neutral-400 hover:text-white hover:bg-[#1a1a22] transition-colors"
              title="بستن سایدبار"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          {/* Scrollable Center: History & In-Store Filters */}
          <div className="flex-1 overflow-y-auto px-3 py-3 space-y-5">
            {/* Real Saved Conversation History */}
            <div>
              <div className="text-[11px] font-bold text-neutral-500 px-2 mb-2">تاریخچه گفتگوها</div>
              {sessions.length === 0 ? (
                <div className="px-3 py-3 rounded-xl bg-[#121218] border border-[#1d1d26] text-[11px] text-neutral-500 text-center">
                  هنوز گفتگویی ثبت نشده است
                </div>
              ) : (
                <div className="space-y-1 max-h-60 overflow-y-auto pr-0.5">
                  {sessions.map((item) => {
                    const isActive = item.sessionId === activeSessionId;
                    return (
                      <div
                        key={item.sessionId}
                        onClick={() => {
                          onSelectSession(item.sessionId);
                          if (window.innerWidth < 768) onClose();
                        }}
                        className={`w-full text-right flex items-center gap-2 px-2.5 py-2 rounded-xl text-xs transition-colors group cursor-pointer ${
                          isActive
                            ? 'bg-[#1b141c] border border-[#e9325a]/40 text-white'
                            : 'text-neutral-300 hover:bg-[#15151c] hover:text-white border border-transparent'
                        }`}
                      >
                        <MessageSquare
                          className={`w-3.5 h-3.5 shrink-0 ${
                            isActive
                              ? 'text-[#ff4d79]'
                              : 'text-neutral-500 group-hover:text-[#ff4d79]'
                          }`}
                        />
                        <span className="truncate flex-1" title={item.title}>
                          {item.title}
                        </span>
                        <button
                          type="button"
                          onClick={(e) => {
                            e.stopPropagation();
                            onDeleteSession(item.sessionId);
                          }}
                          className="opacity-70 md:opacity-0 md:group-hover:opacity-100 p-1 rounded-lg text-neutral-500 hover:text-[#ff4d79] hover:bg-white/5 transition-all shrink-0 cursor-pointer"
                          title="حذف گفتگو"
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* In-Store Live Shopping Filters */}
            <div className="pt-3 border-t border-[#1c1c24]">
              <div className="flex items-center gap-1.5 text-[11px] font-bold text-neutral-400 px-2 mb-2.5">
                <Store className="w-3.5 h-3.5 text-[#e9325a]" />
                <span>فیلترهای خرید حضوری</span>
              </div>

              <div className="space-y-2 px-1">
                <label className="flex items-center justify-between p-2 rounded-xl bg-[#14141a] border border-[#202028] cursor-pointer hover:border-[#2d2d38] transition-colors">
                  <span className="flex items-center gap-2 text-xs text-neutral-300">
                    <Clock className="w-3.5 h-3.5 text-emerald-400" />
                    <span>فقط مغازه‌های باز در این لحظه</span>
                  </span>
                  <input
                    type="checkbox"
                    checked={filterOpenOnly}
                    onChange={(e) => setFilterOpenOnly(e.target.checked)}
                    className="w-4 h-4 accent-[#e9325a] [color-scheme:dark] rounded cursor-pointer"
                  />
                </label>

                <label className="flex items-center justify-between p-2 rounded-xl bg-[#14141a] border border-[#202028] cursor-pointer hover:border-[#2d2d38] transition-colors">
                  <span className="flex items-center gap-2 text-xs text-neutral-300">
                    <CheckCircle2 className="w-3.5 h-3.5 text-[#ff4d79]" />
                    <span>پذیرنده ترب‌پی حضوری</span>
                  </span>
                  <input
                    type="checkbox"
                    checked={filterTorobPay}
                    onChange={(e) => setFilterTorobPay(e.target.checked)}
                    className="w-4 h-4 accent-[#e9325a] [color-scheme:dark] rounded cursor-pointer"
                  />
                </label>

                <label className="flex items-center justify-between p-2 rounded-xl bg-[#14141a] border border-[#202028] cursor-pointer hover:border-[#2d2d38] transition-colors">
                  <span className="flex items-center gap-2 text-xs text-neutral-300">
                    <CreditCard className="w-3.5 h-3.5 text-neutral-400" />
                    <span>خرید اقساطی / اسنپ‌پی</span>
                  </span>
                  <input
                    type="checkbox"
                    checked={filterInstallment}
                    onChange={(e) => setFilterInstallment(e.target.checked)}
                    className="w-4 h-4 accent-[#e9325a] [color-scheme:dark] rounded cursor-pointer"
                  />
                </label>
              </div>
            </div>

            {/* Live 5+1 Adaptive Store RecSys Weights */}
            {activeWeights && activeWeights.length > 0 && (
              <div className="pt-3 border-t border-[#1c1c24]">
                <div className="flex items-center justify-between text-[11px] font-bold text-neutral-400 px-2 mb-2">
                  <span className="flex items-center gap-1.5">
                    <SlidersHorizontal className="w-3.5 h-3.5 text-[#ff4d79]" />
                    <span>وزن‌های تطبیقی فروشگاه (L1=۱۰۰٪)</span>
                  </span>
                  <span className="text-[10px] text-[#ff7597] font-mono">
                    {activeWeights.length.toLocaleString('fa-IR')} پارامتر
                  </span>
                </div>

                <div className="space-y-2 px-1 max-h-56 overflow-y-auto pr-1">
                  {activeWeights.slice(0, 8).map((slot) => (
                    <div
                      key={slot.key}
                      className="p-2 rounded-xl bg-[#13131b] border border-[#20202c] space-y-1"
                    >
                      <div className="flex items-center justify-between text-[11px]">
                        <span className="text-neutral-200 font-semibold truncate">
                          {slot.label_fa}
                        </span>
                        <span className="text-[#ff6688] font-bold font-mono text-[10px]">
                          {Math.round(slot.weight * 100).toLocaleString('fa-IR')}٪
                        </span>
                      </div>
                      {onWeightChange && (
                        <input
                          type="range"
                          min={0.05}
                          max={0.98}
                          step={0.05}
                          value={slot.unconstrained_weight}
                          onChange={(e) =>
                            onWeightChange(slot.key, parseFloat(e.target.value))
                          }
                          className="w-full h-1.5 accent-[#e9325a] cursor-pointer"
                        />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Footer: Generic TorobChat In-Person Profile */}
          <div className="p-3 border-t border-[#1c1c24] bg-[#09090d]">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <TorobLogo size={28} animated={true} withGlow={false} />
                <div>
                  <div className="text-xs font-bold text-neutral-200">کاربر ترب‌چیت</div>
                  <div className="text-[10px] text-neutral-500">خرید حضوری · تهران</div>
                </div>
              </div>
              <span className="text-[10px] text-neutral-600 font-mono">{todayFa}</span>
            </div>
          </div>
        </div>
      </aside>
    </>
  );
};
