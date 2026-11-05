import React, { useState, useEffect } from 'react';
import { ShopOffer } from '../types';
import { generateCallScript, CallSimulationStep } from '../utils/callSimulator';
import { PhoneOff, CheckCircle2, MapPin, Sparkles, Building2, ShieldCheck } from 'lucide-react';

interface VoiceCallModalProps {
  isOpen: boolean;
  onClose: () => void;
  offer: ShopOffer;
  onCallCompleted?: (offerId: string) => void;
}

export const VoiceCallModal: React.FC<VoiceCallModalProps> = ({
  isOpen,
  onClose,
  offer,
  onCallCompleted,
}) => {
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [isCalling, setIsCalling] = useState(true);
  const [isCompleted, setIsCompleted] = useState(false);
  const [script, setScript] = useState<CallSimulationStep[]>([]);

  useEffect(() => {
    if (isOpen) {
      const generated = generateCallScript(offer);
      setScript(generated);
      setCurrentStepIndex(0);
      setIsCalling(true);
      setIsCompleted(false);

      let timeoutId: any;
      let currentIndex = 0;

      const advanceStep = () => {
        if (currentIndex < generated.length - 1) {
          currentIndex++;
          setCurrentStepIndex(currentIndex);
          timeoutId = setTimeout(advanceStep, generated[currentIndex].delayMs);
        } else {
          setIsCalling(false);
          setIsCompleted(true);
          if (onCallCompleted) {
            onCallCompleted(offer.id);
          }
        }
      };

      timeoutId = setTimeout(advanceStep, generated[0].delayMs);

      return () => {
        clearTimeout(timeoutId);
      };
    }
  }, [isOpen, offer]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/85 backdrop-blur-md animate-fade-in font-sans">
      <div className="torob-gradient-border w-full max-w-lg bg-[#0d0d12] border border-[#23232c] rounded-3xl shadow-2xl overflow-hidden flex flex-col max-h-[90vh]">
        {/* Call Header */}
        <div className="bg-[#14141a] p-4.5 border-b border-[#202028] text-center relative">
          <button
            onClick={onClose}
            className="absolute left-3 top-3.5 text-neutral-400 hover:text-white p-1 rounded-xl hover:bg-white/5 transition-colors"
          >
            <PhoneOff className="w-5 h-5 text-[#ff4d79]" />
          </button>

          <div className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-[#e9325a]/15 text-[#ff6688] border border-[#e9325a]/30 text-xs font-bold mb-2">
            <Sparkles className="w-3.5 h-3.5" />
            <span>تماس هوشمند صوتی ترب (Google Call Agent)</span>
          </div>

          <h3 className="text-base font-extrabold text-white mb-0.5">{offer.shopName}</h3>
          <p className="text-xs text-neutral-400 flex items-center justify-center gap-1">
            <Building2 className="w-3.5 h-3.5 text-neutral-500" />
            <span>{offer.mallName} · {offer.mallFloor}</span>
          </p>

          {/* Audio Wave Simulation with Torob colors */}
          <div className="flex items-center justify-center gap-1.5 h-8 mt-3">
            {[40, 75, 30, 95, 60, 85, 45, 90, 35, 70].map((h, i) => (
              <span
                key={i}
                className={`w-1 rounded-full transition-all duration-300 ${
                  isCalling
                    ? 'bg-gradient-to-t from-[#c71f45] to-[#ff4d79] animate-pulse'
                    : 'bg-emerald-500'
                }`}
                style={{
                  height: isCalling ? `${h}%` : '25%',
                  animationDelay: `${i * 80}ms`,
                }}
              />
            ))}
          </div>

          <div className="text-[11px] text-neutral-400 mt-2 font-mono">
            {isCalling ? '📞 در حال مکالمه و راستی‌آزمایی با فروشگاه...' : '✅ مکالمه پایان یافت و اطلاعات استخراج شد'}
          </div>
        </div>

        {/* Live Conversation Transcript */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3 bg-[#0a0a0e]">
          {script.slice(0, currentStepIndex + 1).map((step, idx) => {
            const isAgent = step.speaker === 'ایجنت ترب';
            return (
              <div
                key={idx}
                className={`flex flex-col ${isAgent ? 'items-start' : 'items-end'} transition-all duration-300`}
              >
                <span className="text-[10px] text-neutral-500 mb-1 px-1">
                  {step.speaker}
                </span>
                <div
                  className={`max-w-[85%] rounded-2xl px-3.5 py-2.5 text-xs leading-relaxed ${
                    isAgent
                      ? 'bg-[#14141b] text-neutral-200 border border-[#22222b] rounded-tr-xs'
                      : 'bg-[#221319] text-rose-100 border border-[#e9325a]/30 rounded-tl-xs'
                  }`}
                >
                  {step.text}
                </div>
              </div>
            );
          })}
        </div>

        {/* Call Summary & Extracted Intelligence */}
        {isCompleted && (
          <div className="p-4 bg-[#14141a] border-t border-[#202028] space-y-3 animate-fade-in">
            <div className="flex items-center gap-2 text-xs font-bold text-emerald-400">
              <ShieldCheck className="w-4 h-4" />
              <span>نتیجه استعلام هوشمند لحظه‌ای:</span>
            </div>

            <div className="grid grid-cols-2 gap-2 text-xs">
              <div className="bg-[#0e0e13] p-2.5 rounded-xl border border-[#202028]">
                <span className="text-neutral-500 text-[11px] block">قیمت قطعی تأییدشده:</span>
                <span className="font-black text-white text-sm">
                  {(offer.price).toLocaleString('fa-IR')} تومان
                </span>
              </div>
              <div className="bg-[#0e0e13] p-2.5 rounded-xl border border-[#202028]">
                <span className="text-neutral-500 text-[11px] block">وضعیت موجودی انبار:</span>
                <span className="font-bold text-emerald-400 flex items-center gap-1">
                  <CheckCircle2 className="w-3.5 h-3.5" />
                  موجود و آماده تحویل فوری
                </span>
              </div>
            </div>

            <div className="p-2.5 rounded-xl bg-[#0e0e13] border border-[#202028] text-[11px] text-neutral-300 flex items-start gap-1.5">
              <MapPin className="w-3.5 h-3.5 text-[#e9325a] shrink-0 mt-0.5" />
              <div>
                <span className="font-bold text-white">راهنمای مراجعه در پاساژ: </span>
                {offer.mallName} · {offer.mallFloor} · {offer.mallUnit} ({offer.mallNote})
              </div>
            </div>

            <button
              onClick={onClose}
              className="w-full py-2.5 rounded-xl bg-[#e9325a] hover:bg-[#d8244c] text-white text-xs font-bold shadow-md shadow-[#e9325a]/30 transition-colors"
            >
              متوجه شدم و اطلاعات ثبت شد
            </button>
          </div>
        )}
      </div>
    </div>
  );
};
