import React from 'react';
import { ActiveTab, UserLocation } from '../types';
import { MessageSquareText, Store, Clock, Swords, MapPin } from 'lucide-react';
import { motion, AnimatePresence } from 'motion/react';
import { TorobLogo } from './TorobLogo';

interface HeaderProps {
  activeTab: ActiveTab;
  setActiveTab: (tab: ActiveTab) => void;
  showTabs: boolean;
  onToggleSidebar: () => void;
  isSidebarOpen: boolean;
  userLocation: UserLocation;
  onOpenLocationPicker: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  setActiveTab,
  showTabs,
  onToggleSidebar,
  isSidebarOpen,
  userLocation,
  onOpenLocationPicker,
}) => {
  const tabs = [
    {
      id: 'chat' as ActiveTab,
      tooltip: 'گفتگو و مشاوره خرید',
      icon: MessageSquareText,
    },
    {
      id: 'stores' as ActiveTab,
      tooltip: 'فروشگاه‌ها و مراکز خرید تهران',
      icon: Store,
    },
    {
      id: 'compare' as ActiveTab,
      tooltip: 'نبرد و مقایسه مدل‌ها و جدول مشخصات',
      icon: Swords,
    },
  ];

  return (
    <header className="sticky top-0 z-40 bg-[#0d0d12]/95 backdrop-blur-md border-b border-[#1c1c24] px-4 py-2.5 transition-all">
      <div className="max-w-7xl mx-auto flex items-center justify-between gap-4">
        {/* Right side: Animated Torob Logo & Title ONLY */}
        <div className="flex items-center">
          <div
            className="flex items-center gap-2 cursor-pointer select-none group"
            onClick={() => setActiveTab('chat')}
          >
            {/* Animated Torob Radish Mascot Logo */}
            <TorobLogo size={32} animated={true} />

            <span className="font-black text-base text-white tracking-tight group-hover:text-[#ff4d79] transition-colors">
              ترب‌چیت
            </span>
          </div>
        </div>

        {/* Center: Navigation Tabs (Icon-only, compact, clear, and expressive) */}
        <div className="flex items-center justify-center min-h-[38px]">
          <AnimatePresence>
            {showTabs && (
              <motion.div
                initial={{ opacity: 0, y: -10, scale: 0.95 }}
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={{ opacity: 0, y: -10, scale: 0.95 }}
                transition={{ duration: 0.3 }}
                className="flex items-center gap-1.5 bg-[#14141a] p-1 rounded-2xl border border-[#202028] relative shadow-inner"
              >
                {tabs.map((tab) => {
                  const isActive = activeTab === tab.id;
                  const Icon = tab.icon;

                  return (
                    <button
                      key={tab.id}
                      onClick={() => setActiveTab(tab.id)}
                      title={tab.tooltip}
                      className={`relative p-2.5 sm:px-3.5 sm:py-2 rounded-xl transition-all z-10 flex items-center justify-center ${
                        isActive
                          ? 'text-white'
                          : 'text-neutral-400 hover:text-white hover:bg-white/[0.04]'
                      }`}
                    >
                      {/* Sliding Pink Indicator */}
                      {isActive && (
                        <motion.div
                          layoutId="activeTabIndicator"
                          className="absolute inset-0 bg-[#e9325a] rounded-xl shadow-lg shadow-[#e9325a]/35 -z-10"
                          transition={{
                            type: 'spring',
                            stiffness: 450,
                            damping: 32,
                          }}
                        />
                      )}

                      <Icon className="w-5 h-5 shrink-0" />
                    </button>
                  );
                })}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* Left side: Location Picker Pill + History Button */}
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onOpenLocationPicker}
            title="انتخاب دستی موقعیت مکانی روی نقشه تهران"
            className="px-2.5 py-2 rounded-xl bg-[#14141e] hover:bg-[#1b1b29] text-neutral-200 hover:text-white border border-[#252535] hover:border-[#ff4d79]/60 transition-all flex items-center gap-1.5 text-xs font-bold max-w-[165px] sm:max-w-[230px] cursor-pointer"
          >
            <MapPin className="w-3.5 h-3.5 text-[#ff4d79] shrink-0" />
            <span className="truncate">{userLocation.name}</span>
          </button>

          <button
            onClick={onToggleSidebar}
            title={isSidebarOpen ? 'بستن تاریخچه' : 'تاریخچه گفتگوها'}
            className={`p-2 sm:p-2.5 rounded-xl transition-all flex items-center justify-center border ${
              isSidebarOpen
                ? 'bg-[#e9325a] text-white border-[#e9325a] shadow-md shadow-[#e9325a]/30 scale-105'
                : 'bg-[#14141e] text-neutral-400 hover:text-white border-[#252535] hover:border-[#ff4d79]/60 hover:bg-[#1a1a26]'
            }`}
          >
            <Clock className="w-4 h-4" />
          </button>
        </div>
      </div>
    </header>
  );
};


