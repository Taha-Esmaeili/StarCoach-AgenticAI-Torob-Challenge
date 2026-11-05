import React, { useState } from 'react';
import { ShopOffer } from '../types';
import {
  Phone,
  PhoneCall,
  Copy,
  Check,
  Instagram,
  Globe,
  Clock,
  MapPin,
  X,
  Store,
  Info,
} from 'lucide-react';

interface StoreContactModalProps {
  isOpen: boolean;
  onClose: () => void;
  offer: ShopOffer;
}

export const StoreContactModal: React.FC<StoreContactModalProps> = ({
  isOpen,
  onClose,
  offer,
}) => {
  const [copiedPhone, setCopiedPhone] = useState(false);

  if (!isOpen) return null;

  // Extract digits for tel: link (e.g. 02166762450)
  const numericPhone = offer.phone.replace(/[^0-9]/g, '');
  // Convert Persian numbers to English if needed for tel: protocol
  const telNumber = numericPhone.replace(/[۰-۹]/g, (d) =>
    '۰۱۲۳۴۵۶۷۸۹'.indexOf(d).toString()
  );

  const handleCopyPhone = () => {
    navigator.clipboard?.writeText(offer.phone);
    setCopiedPhone(true);
    setTimeout(() => setCopiedPhone(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm animate-fade-in font-sans select-none">
      <div className="relative w-full max-w-md bg-[#14141d] border border-[#2b2b3b] rounded-3xl shadow-2xl overflow-hidden animate-scale-up">
        {/* Header */}
        <div className="p-4 sm:p-5 border-b border-[#222230] bg-[#181822] flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-2xl bg-[#e9325a]/15 border border-[#e9325a]/30 flex items-center justify-center text-[#ff6688]">
              <Store className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm sm:text-base font-extrabold text-white">
                  {offer.shopName}
                </h3>
                {offer.isRealShop && (
                  <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-md bg-emerald-500/15 text-emerald-400 border border-emerald-500/30">
                    رسمی
                  </span>
                )}
              </div>
              <span className="text-xs text-neutral-400 block mt-0.5">
                {offer.mallName || offer.neighborhood}
              </span>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-2 rounded-xl text-neutral-400 hover:text-white hover:bg-[#20202e] transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-4 sm:p-5 space-y-4 text-xs">
          {/* Direct Phone Call Card */}
          <div className="p-4 rounded-2xl bg-[#191924] border border-[#262636] space-y-3">
            <div className="flex items-center justify-between">
              <span className="text-neutral-400 font-medium">شماره تماس مستقیم فروشگاه:</span>
              <span className="text-white font-extrabold text-sm tracking-wider">
                {offer.phone}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-2 pt-1">
              {/* Click to Call */}
              <a
                href={`tel:${telNumber || offer.phone}`}
                className="py-2.5 px-3 rounded-xl bg-[#e9325a] hover:bg-[#ff2d5f] text-white font-bold text-xs flex items-center justify-center gap-2 shadow-md shadow-[#e9325a]/25 transition-all"
              >
                <PhoneCall className="w-4 h-4" />
                <span>تماس مستقیم</span>
              </a>

              {/* Copy Phone */}
              <button
                onClick={handleCopyPhone}
                className="py-2.5 px-3 rounded-xl bg-[#20202c] hover:bg-[#282838] border border-[#2e2e40] text-neutral-200 font-bold text-xs flex items-center justify-center gap-2 transition-colors"
              >
                {copiedPhone ? (
                  <>
                    <Check className="w-4 h-4 text-emerald-400" />
                    <span className="text-emerald-400">کپی شد!</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-4 h-4 text-neutral-400" />
                    <span>کپی شماره</span>
                  </>
                )}
              </button>
            </div>
          </div>

          {/* Social / Web Channels */}
          <div className="space-y-2">
            {offer.instagramHandle && (
              <a
                href={`https://instagram.com/${offer.instagramHandle.replace('@', '')}`}
                target="_blank"
                rel="noopener noreferrer"
                className="p-3 rounded-xl bg-[#171722] hover:bg-[#1e1e2c] border border-[#252536] flex items-center justify-between text-neutral-200 transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <div className="w-7 h-7 rounded-lg bg-pink-500/15 text-pink-400 flex items-center justify-center">
                    <Instagram className="w-4 h-4" />
                  </div>
                  <div>
                    <span className="font-bold text-xs block text-white">
                      صفحه اینستاگرام فروشگاه
                    </span>
                    <span className="text-[11px] text-neutral-400">
                      {offer.instagramHandle}
                    </span>
                  </div>
                </div>
                <span className="text-[11px] text-[#ff80a0] font-bold">مشاهده صفحه</span>
              </a>
            )}

            {offer.websiteUrl && (
              <a
                href={offer.websiteUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="p-3 rounded-xl bg-[#171722] hover:bg-[#1e1e2c] border border-[#252536] flex items-center justify-between text-neutral-200 transition-colors"
              >
                <div className="flex items-center gap-2.5">
                  <div className="w-7 h-7 rounded-lg bg-blue-500/15 text-blue-400 flex items-center justify-center">
                    <Globe className="w-4 h-4" />
                  </div>
                  <div>
                    <span className="font-bold text-xs block text-white">وب‌سایت فروشگاه</span>
                    <span className="text-[11px] text-neutral-400 truncate max-w-[180px] block">
                      {offer.websiteUrl}
                    </span>
                  </div>
                </div>
                <span className="text-[11px] text-blue-400 font-bold">ورود به سایت</span>
              </a>
            )}
          </div>

          {/* Location & Working Hours */}
          <div className="p-3 rounded-xl bg-[#171722] border border-[#252536] space-y-2 text-[11px]">
            <div className="flex items-center justify-between">
              <span className="text-neutral-400 flex items-center gap-1.5">
                <Clock className="w-3.5 h-3.5 text-neutral-400" />
                ساعات کاری و پاسخگویی:
              </span>
              <span className="font-bold text-white">{offer.workingHours}</span>
            </div>

            <div className="pt-2 border-t border-[#222230] flex items-start gap-1.5 text-neutral-300">
              <MapPin className="w-3.5 h-3.5 text-[#ff4d79] shrink-0 mt-0.5" />
              <span className="leading-relaxed">{offer.address}</span>
            </div>
          </div>

          {/* Practical Calling Tips */}
          <div className="p-3 rounded-xl bg-[#14141c] border border-[#22222e] text-[11px] text-neutral-400 flex items-start gap-2">
            <Info className="w-3.5 h-3.5 text-neutral-400 shrink-0 mt-0.5" />
            <span className="leading-relaxed">
              پیشنهاد می‌شود قبل از مراجعه، موجودی رنگ دلخواه و شرایط گارانتی را با فروشگاه چک
              بفرمایید.
            </span>
          </div>
        </div>
      </div>
    </div>
  );
};
