import React, { useState } from 'react';
import { Product } from '../types';
import { PRODUCTS } from '../data/mockData';
import { ArrowLeft, ChevronDown, Check, Zap, Gauge, BatteryCharging, Swords } from 'lucide-react';

interface ComparisonViewProps {
  selectedProduct: Product;
  onSelectProduct: (p: Product) => void;
  onNavigateToStores: () => void;
}

export const ComparisonView: React.FC<ComparisonViewProps> = ({
  selectedProduct,
  onSelectProduct,
  onNavigateToStores,
}) => {
  const [showFullSpecs, setShowFullSpecs] = useState(false);
  const scooters = PRODUCTS.filter((p) => p.category === 'اسکوتر برقی');

  const detailedSpecs = [
    { label: 'وزن دستگاه', key: 'وزن دستگاه' },
    { label: 'سیستم ترمز و تعلیق', key: 'سیستم ترمز' },
    { label: 'مناسب برای', key: 'bestFor' },
    { label: 'قابلیت تاشو', key: 'قابلیت تاشو' },
  ];

  return (
    <div className="flex-1 overflow-y-auto p-4 md:p-6 bg-[#0c0c10] space-y-5 font-sans select-none">
      <div className="max-w-4xl mx-auto space-y-4">
        {/* Simple & Clean Header with Combat / Battle Icon */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-[#1f1f2a] pb-3">
          <div>
            <h2 className="text-base md:text-lg font-black text-white flex items-center gap-2">
              <Swords className="w-5 h-5 text-[#ff4d79]" />
              <span>نبرد و مقایسه مدل‌های بازار</span>
            </h2>
            <p className="text-xs text-neutral-400 mt-0.5">
              مقایسه قیمت و مشخصات کلیدی برای انتخاب بهترین گزینه در خرید حضوری
            </p>
          </div>
          <span className="text-xs text-neutral-400 self-start sm:self-auto font-medium">
            {scooters.length} مدل محبوب
          </span>
        </div>

        {/* Simplified Side-by-Side Product Cards */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {scooters.map((scooter) => {
            const isCurrent = scooter.id === selectedProduct.id;

            return (
              <div
                key={scooter.id}
                onClick={() => onSelectProduct(scooter)}
                className={`p-4 rounded-2xl transition-all duration-200 cursor-pointer flex flex-col justify-between ${
                  isCurrent
                    ? 'bg-[#181822] border-2 border-[#e9325a] shadow-lg shadow-[#e9325a]/15'
                    : 'bg-[#14141a] border border-[#22222d] hover:border-[#353545]'
                }`}
              >
                <div className="space-y-3">
                  {/* Compact Header: Image + Title */}
                  <div className="flex items-center gap-3">
                    <div className="w-14 h-14 rounded-xl overflow-hidden bg-black border border-[#282836] shrink-0">
                      <img
                        src={scooter.image}
                        alt={scooter.title}
                        className="w-full h-full object-cover"
                      />
                    </div>
                    <div className="min-w-0">
                      {isCurrent ? (
                        <span className="text-[10px] text-[#ff80a0] font-bold px-2 py-0.5 rounded-full bg-[#e9325a]/15 border border-[#e9325a]/30 inline-block mb-1">
                          مدل انتخابی
                        </span>
                      ) : (
                        <span className="text-[10px] text-neutral-400 font-medium px-2 py-0.5 rounded-full bg-[#1c1c25] border border-[#282834] inline-block mb-1">
                          {scooter.brand.split(' ')[0]}
                        </span>
                      )}
                      <h3 className="font-extrabold text-xs md:text-sm text-white line-clamp-2 leading-tight">
                        {scooter.title}
                      </h3>
                    </div>
                  </div>

                  {/* Price Banner */}
                  <div className="p-2.5 rounded-xl bg-[#191924] border border-[#252536] flex items-center justify-between">
                    <span className="text-[11px] text-neutral-400">کف قیمت تهران:</span>
                    <span className="text-sm font-black text-white">
                      {scooter.minPrice.toLocaleString('fa-IR')}
                      <span className="text-[10px] font-normal text-neutral-400 mr-1">تومان</span>
                    </span>
                  </div>

                  {/* Primary 3 Key Decision Specs */}
                  <div className="space-y-1.5 text-xs">
                    <div className="flex items-center justify-between py-1 border-b border-[#1f1f2a]">
                      <span className="text-neutral-400 flex items-center gap-1.5 text-[11px]">
                        <Gauge className="w-3.5 h-3.5 text-amber-400" />
                        حداکثر سرعت:
                      </span>
                      <span className="font-bold text-white text-[11px]">
                        {scooter.specs['حداکثر سرعت'] || '—'}
                      </span>
                    </div>

                    <div className="flex items-center justify-between py-1 border-b border-[#1f1f2a]">
                      <span className="text-neutral-400 flex items-center gap-1.5 text-[11px]">
                        <BatteryCharging className="w-3.5 h-3.5 text-emerald-400" />
                        برد مسافتی:
                      </span>
                      <span className="font-bold text-white text-[11px]">
                        {scooter.specs['برد مسافتی'] || '—'}
                      </span>
                    </div>

                    <div className="flex items-center justify-between py-1">
                      <span className="text-neutral-400 flex items-center gap-1.5 text-[11px]">
                        <Zap className="w-3.5 h-3.5 text-[#ff4d79]" />
                        توان موتور:
                      </span>
                      <span className="font-bold text-white text-[11px]">
                        {scooter.specs['توان موتور'] || '—'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Card Action Button */}
                <div className="mt-4 pt-3 border-t border-[#1f1f2a]">
                  {isCurrent ? (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onNavigateToStores();
                      }}
                      className="w-full py-2 rounded-xl bg-[#e9325a] hover:bg-[#ff2d5f] text-white text-xs font-bold flex items-center justify-center gap-1.5 shadow-md shadow-[#e9325a]/25 transition-all"
                    >
                      <span>مشاهده فروشگاه‌ها</span>
                      <ArrowLeft className="w-3.5 h-3.5" />
                    </button>
                  ) : (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onSelectProduct(scooter);
                      }}
                      className="w-full py-2 rounded-xl bg-[#1b1b24] hover:bg-[#232330] border border-[#282836] text-xs text-neutral-300 font-bold transition-all"
                    >
                      انتخاب این مدل
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Expandable Full Comparison Matrix */}
        <div className="pt-2">
          <button
            onClick={() => setShowFullSpecs(!showFullSpecs)}
            className="w-full p-3 rounded-2xl bg-[#14141a] hover:bg-[#181822] border border-[#22222d] text-xs font-bold text-neutral-300 flex items-center justify-center gap-2 transition-all cursor-pointer group"
          >
            <Swords className="w-4 h-4 text-[#ff4d79] group-hover:scale-110 transition-transform" />
            <span>{showFullSpecs ? 'بستن جدول مشخصات و نبرد کامل' : 'مشاهده جدول نبرد و مقایسه جزئیات فنی'}</span>
            <ChevronDown
              className={`w-4 h-4 text-[#ff4d79] transition-transform duration-200 ${
                showFullSpecs ? 'rotate-180' : ''
              }`}
            />
          </button>

          {showFullSpecs && (
            <div className="mt-3 rounded-2xl bg-[#14141a] border border-[#22222d] overflow-hidden shadow-xl animate-fade-in">
              <div className="overflow-x-auto">
                <table className="w-full text-right text-xs">
                  <thead>
                    <tr className="border-b border-[#20202a] bg-[#171720] text-neutral-300">
                      <th className="p-3 w-1/3 font-bold">مشخصه فنی</th>
                      {scooters.map((s) => (
                        <th
                          key={s.id}
                          className={`p-3 font-bold ${
                            s.id === selectedProduct.id ? 'text-[#ff6688]' : 'text-white'
                          }`}
                        >
                          {s.title.split('مدل')[0]}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#1e1e28] text-neutral-300">
                    {detailedSpecs.map((spec, idx) => (
                      <tr key={idx} className="hover:bg-white/[0.02]">
                        <td className="p-3 font-medium text-neutral-400">{spec.label}</td>
                        {scooters.map((s) => {
                          let val = '';
                          if (spec.key === 'bestFor') {
                            val = s.bestFor;
                          } else {
                            val = s.specs[spec.key] || s.specs['سیستم تعلیق'] || 'استاندارد';
                          }

                          return (
                            <td
                              key={s.id}
                              className={`p-3 text-[11px] leading-relaxed ${
                                s.id === selectedProduct.id
                                  ? 'text-white font-semibold bg-[#e9325a]/5'
                                  : 'text-neutral-300'
                              }`}
                            >
                              {val}
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
