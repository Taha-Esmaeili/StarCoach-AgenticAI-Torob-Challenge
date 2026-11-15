import React, { useMemo } from 'react';
import { Product, ShopOffer } from '../types';
import { PRODUCTS } from '../data/mockData';
import { Check, X, Store, Sparkles, Swords } from 'lucide-react';

interface ComparisonViewProps {
  products?: Product[];
  onSelectProductForStores: (product: Product) => void;
  offers: ShopOffer[];
}

export const ComparisonView: React.FC<ComparisonViewProps> = ({
  products,
  onSelectProductForStores,
  offers,
}) => {
  // Use live recommendedProducts from backend when available, otherwise fall back to template products
  const comparedProducts = useMemo(() => {
    if (products && products.length > 0) {
      return products.slice(0, 3);
    }
    return PRODUCTS.filter((p) => p.category === 'اسکوتر برقی').slice(0, 3);
  }, [products]);

  const activeCategoryName = comparedProducts[0]?.category || 'محصولات منتخب';

  // Dynamically extract up to 6 shared/informative spec keys from the active products (`T025`)
  const dynamicSpecKeys = useMemo(() => {
    const keyCounts = new Map<string, number>();
    comparedProducts.forEach((p) => {
      Object.keys(p.specs || {}).forEach((k) => {
        keyCounts.set(k, (keyCounts.get(k) || 0) + 1);
      });
    });
    return Array.from(keyCounts.entries())
      .sort((a, b) => b[1] - a[1])
      .slice(0, 6)
      .map(([k]) => k);
  }, [comparedProducts]);

  return (
    <div className="flex-1 overflow-y-auto p-4 md:p-6 bg-[#0c0c10] font-sans">
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div className="p-4 rounded-2xl bg-[#13131a] border border-[#1f1f2a] flex items-center justify-between flex-wrap gap-3">
          <div>
            <div className="flex items-center gap-2">
              <Swords className="w-5 h-5 text-[#e9325a]" />
              <h2 className="text-base md:text-xl font-extrabold text-white">
                نبرد و مقایسه تخصصی مدل‌های «{activeCategoryName}» برای خرید حضوری در تهران
              </h2>
            </div>
            <p className="text-[13px] sm:text-sm text-neutral-400 mt-1 leading-relaxed">
              مقایسه مشخصات فنی واقعی کاتالوگ ترب، تعداد مغازه‌های دارای موجودی حضوری و کف قیمت بازار تهران
            </p>
          </div>
          <span className="text-xs sm:text-[13px] font-bold text-[#ff7597] bg-[#e9325a]/15 border border-[#e9325a]/30 px-3 py-1 rounded-xl">
            {comparedProducts.length.toLocaleString('fa-IR')} مدل برگزیده
          </span>
        </div>

        {/* Comparison Cards Grid */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {comparedProducts.map((product, index) => {
            const productOffers = offers.filter((o) => o.productId === product.id);
            const openCount = productOffers.filter((o) => o.isOpenNow).length;

            return (
              <div
                key={product.id}
                className={`p-4 sm:p-5 rounded-2xl flex flex-col justify-between border transition-all ${
                  index === 0
                    ? 'torob-gradient-border bg-[#14141d]'
                    : 'bg-[#121219] border-[#20202c]'
                }`}
              >
                <div className="space-y-4">
                  {/* Top Badge */}
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-xs font-bold px-2.5 py-0.5 rounded-lg bg-[#e9325a]/15 text-[#ff4d79] border border-[#e9325a]/30 flex items-center gap-1">
                      <Sparkles className="w-3.5 h-3.5" />
                      {product.badge || (index === 0 ? 'بهترین ارزش خرید' : 'گزینه جایگزین')}
                    </span>
                    <span className="text-xs text-neutral-400">
                      امتیاز تطابق: <strong className="text-white">{product.rating}</strong>
                    </span>
                  </div>

                  {/* Product Image & Title */}
                  {product.image && (
                    <div className="w-full h-36 rounded-xl overflow-hidden bg-[#0d0d14] border border-white/5">
                      <img
                        src={product.image}
                        alt={product.title}
                        className="w-full h-full object-cover"
                        loading="lazy"
                      />
                    </div>
                  )}

                  <div>
                    <h3 className="text-[15px] sm:text-base font-black text-white leading-relaxed">
                      {product.title}
                    </h3>
                    <p className="text-[13px] sm:text-sm text-neutral-400 mt-1 leading-relaxed">
                      {product.bestFor}
                    </p>
                  </div>

                  {/* Price Box */}
                  <div className="p-3.5 rounded-xl bg-[#0d0d13] border border-[#1d1d26]">
                    <div className="text-xs text-neutral-400">بازه قیمت حضوری در تهران:</div>
                    <div className="text-base sm:text-lg font-extrabold text-[#ff4d79] mt-0.5">
                      از {product.minPrice.toLocaleString('fa-IR')} تومان
                    </div>
                    <div className="text-xs text-neutral-400 mt-1 flex items-center gap-1.5">
                      <Store className="w-3.5 h-3.5 text-emerald-400" />
                      <span>
                        موجود در {product.storeCount.toLocaleString('fa-IR')} فروشگاه حضوری (
                        {(openCount || product.storeCount).toLocaleString('fa-IR')} مغازه فعال)
                      </span>
                    </div>
                  </div>

                  {/* Dynamic Category Specs Table (`T025`) */}
                  {dynamicSpecKeys.length > 0 && (
                    <div className="space-y-1.5 text-[13px] sm:text-sm">
                      <div className="text-xs sm:text-[13px] font-bold text-neutral-400 mb-1">
                        مشخصات کلیدی کاتالوگ:
                      </div>
                      {dynamicSpecKeys.map((specKey) => (
                        <div
                          key={specKey}
                          className="flex justify-between gap-2 py-1.5 border-b border-[#1c1c26]"
                        >
                          <span className="text-neutral-400">{specKey}:</span>
                          <span className="font-semibold text-neutral-200 text-left">
                            {product.specs[specKey] || '—'}
                          </span>
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Pros & Cons */}
                  <div className="space-y-2 pt-1">
                    <div className="text-xs sm:text-[13px] font-bold text-emerald-400">
                      نقاط قوت:
                    </div>
                    <ul className="space-y-1.5">
                      {product.pros.map((pro, idx) => (
                        <li
                          key={idx}
                          className="text-xs sm:text-[13px] text-neutral-300 flex items-start gap-1.5 leading-relaxed"
                        >
                          <Check className="w-4 h-4 text-emerald-400 shrink-0 mt-0.5" />
                          <span>{pro}</span>
                        </li>
                      ))}
                    </ul>

                    <div className="text-xs sm:text-[13px] font-bold text-rose-400 pt-1">
                      ملاحظات خرید:
                    </div>
                    <ul className="space-y-1.5">
                      {product.cons.map((con, idx) => (
                        <li
                          key={idx}
                          className="text-xs sm:text-[13px] text-neutral-400 flex items-start gap-1.5 leading-relaxed"
                        >
                          <X className="w-4 h-4 text-rose-400 shrink-0 mt-0.5" />
                          <span>{con}</span>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>

                {/* Action Button */}
                <button
                  onClick={() => onSelectProductForStores(product)}
                  className="mt-5 w-full py-2.5 px-4 rounded-xl bg-[#e9325a] hover:bg-[#d6254d] text-white text-[13px] sm:text-sm font-bold transition-colors flex items-center justify-center gap-1.5 cursor-pointer"
                >
                  <Store className="w-4 h-4" />
                  <span>مشاهده مغازه‌های حضوری این مدل</span>
                </button>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
};
