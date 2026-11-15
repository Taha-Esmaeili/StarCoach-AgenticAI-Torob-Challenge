import React, { useState } from 'react';
import { FeatureClarificationPayload, FeatureQuestion } from '../types';
import {
  Clock,
  MapPin,
  CreditCard,
  Target,
  CheckCircle2,
  Edit3,
  SendHorizontal,
} from 'lucide-react';

interface FeatureClarificationCardProps {
  payload: FeatureClarificationPayload;
  messageId: string;
  onSubmit: (answers: Record<string, string>) => void;
}

export const FeatureClarificationCard: React.FC<FeatureClarificationCardProps> = ({
  payload,
  messageId,
  onSubmit,
}) => {
  const [answers, setAnswers] = useState<Record<string, string>>(
    payload.submittedAnswers || {}
  );
  const [isEditing, setIsEditing] = useState<boolean>(!payload.isSubmitted);

  const getIcon = (type: FeatureQuestion['iconType']) => {
    switch (type) {
      case 'time':
        return <Clock className="w-3.5 h-3.5 text-[#ff80a0]" />;
      case 'location':
        return <MapPin className="w-3.5 h-3.5 text-amber-400" />;
      case 'payment':
        return <CreditCard className="w-3.5 h-3.5 text-emerald-400" />;
      case 'usage':
      default:
        return <Target className="w-3.5 h-3.5 text-sky-400" />;
    }
  };

  const handleSelectOption = (questionId: string, option: string) => {
    setAnswers((prev) => ({
      ...prev,
      [questionId]: option,
    }));
  };

  const handleCustomInputChange = (questionId: string, value: string) => {
    setAnswers((prev) => ({
      ...prev,
      [questionId]: value,
    }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setIsEditing(false);
    onSubmit(answers);
  };

  // If already submitted and user is not in editing mode, show summary card
  if (payload.isSubmitted && !isEditing) {
    return (
      <div className="mt-4 p-4 rounded-2xl bg-gradient-to-b from-[#1b1b26] to-[#12121a] border border-[#2e2e42] shadow-lg animate-fade-in text-right">
        <div className="flex items-center justify-between pb-3 mb-3 border-b border-[#28283a] gap-2 flex-wrap">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-4 h-4 text-emerald-400" />
            <span className="text-[13px] sm:text-sm font-black text-white">
              مشخصات ثبت‌شده برای الگوریتم رتبه‌بندی {payload.categoryTitle}:
            </span>
          </div>
          <button
            onClick={() => setIsEditing(true)}
            className="flex items-center gap-1.5 text-xs font-bold text-[#ff6688] hover:text-[#ff4d79] transition-colors bg-[#ff4d79]/10 px-2.5 py-1 rounded-lg border border-[#ff4d79]/20 cursor-pointer"
          >
            <Edit3 className="w-3.5 h-3.5" />
            <span>ویرایش مشخصات</span>
          </button>
        </div>

        {/* Display selected tags */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 text-sm">
          {payload.questions.map((q) => {
            const val = answers[q.id] || payload.submittedAnswers?.[q.id] || 'مشخص نشده';
            return (
              <div
                key={q.id}
                className="flex items-start gap-2.5 p-3 rounded-xl bg-[#151520] border border-[#242434]"
              >
                <div className="p-1.5 rounded-md bg-[#202030] mt-0.5">
                  {getIcon(q.iconType)}
                </div>
                <div className="min-w-0 flex-1">
                  <span className="text-xs text-neutral-400 block font-medium">
                    {q.title}:
                  </span>
                  <span className="font-bold text-white text-[13px] sm:text-sm truncate block mt-0.5" title={val}>
                    {val}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
  }

  return (
    <div className="mt-4 p-4 md:p-5 rounded-2xl bg-gradient-to-b from-[#181824] via-[#14141e] to-[#0f0f16] border-2 border-[#ff4d79]/40 shadow-xl shadow-black/60 animate-fade-in text-right">
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* List of distinct Question Cards - each question has its own dedicated answer input box directly under it */}
        {payload.questions.map((q, idx) => {
          const currentAnswer = answers[q.id] || '';
          const hasAnswer = currentAnswer.trim().length > 0;

          return (
            <div
              key={q.id}
              className={`p-4 rounded-xl border transition-all ${
                hasAnswer
                  ? 'bg-[#181826] border-[#e9325a]/40 shadow-sm'
                  : 'bg-[#14141e] border-[#252536] hover:border-[#383852]'
              }`}
            >
              {/* Question Header: Number + Title + Impact Badge */}
              <div className="flex items-center justify-between gap-2 mb-2.5 flex-wrap">
                <div className="flex items-center gap-2">
                  <span className="w-6 h-6 rounded-full bg-[#e9325a] text-white text-xs font-black flex items-center justify-center shrink-0">
                    {(idx + 1).toLocaleString('fa-IR')}
                  </span>
                  <span className="font-extrabold text-sm text-white">
                    {q.title}
                  </span>
                </div>

                {/* Impact Badge */}
                <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-[#222234] border border-[#36364c] text-xs text-neutral-200">
                  {getIcon(q.iconType)}
                  <span>{q.impactBadge}</span>
                </span>
              </div>

              {/* Question description */}
              <p className="text-sm text-neutral-200 font-semibold mb-3 leading-relaxed">
                {q.question}
              </p>

              {/* Quick Selectable Option Chips */}
              <div className="flex flex-wrap gap-2 mb-3">
                {q.options.map((opt, oIdx) => {
                  const isSelected = currentAnswer === opt;
                  return (
                    <button
                      key={oIdx}
                      type="button"
                      onClick={() => handleSelectOption(q.id, opt)}
                      className={`px-3.5 py-2 rounded-xl text-[13px] sm:text-sm font-medium transition-all text-right flex items-center gap-1.5 cursor-pointer ${
                        isSelected
                          ? 'bg-[#e9325a] text-white border border-[#ff4d79] shadow-sm shadow-[#e9325a]/30'
                          : 'bg-[#1c1c2a] hover:bg-[#252538] text-neutral-200 hover:text-white border border-[#2e2e42]'
                      }`}
                    >
                      {isSelected && <CheckCircle2 className="w-3.5 h-3.5 text-white" />}
                      <span>{opt}</span>
                    </button>
                  );
                })}
              </div>

              {/* DEDICATED INDIVIDUAL INPUT BOX DIRECTLY UNDERNEATH THIS QUESTION */}
              <div className="relative mt-2">
                <input
                  type="text"
                  value={currentAnswer}
                  onChange={(e) => handleCustomInputChange(q.id, e.target.value)}
                  placeholder={q.placeholder}
                  className="w-full bg-[#0d0d14] border border-[#2c2c3e] focus:border-[#e9325a] focus:ring-1 focus:ring-[#e9325a] rounded-xl px-3.5 py-2.5 text-sm text-white placeholder-neutral-400 transition-colors"
                />
                {currentAnswer && (
                  <button
                    type="button"
                    onClick={() => handleCustomInputChange(q.id, '')}
                    className="absolute left-2.5 top-1/2 -translate-y-1/2 text-neutral-400 hover:text-neutral-200 text-xs bg-[#1e1e2c] px-2 py-0.5 rounded"
                  >
                    پاک کردن
                  </button>
                )}
              </div>
            </div>
          );
        })}

        {/* Action Button at bottom: Send Icon Button */}
        <div className="pt-2 flex items-center justify-end border-t border-[#252536]">
          <button
            type="submit"
            title="ارسال پاسخ‌ها"
            className="p-2.5 rounded-xl bg-gradient-to-r from-[#e9325a] to-[#ff4d79] hover:from-[#ff2d5f] hover:to-[#ff5c85] text-white shadow-lg shadow-[#e9325a]/30 hover:scale-105 active:scale-95 transition-all flex items-center justify-center cursor-pointer"
          >
            <SendHorizontal className="w-4 h-4" />
          </button>
        </div>
      </form>
    </div>
  );
};
