import React, { useState } from 'react';
import { ShopOffer, Product } from '../types';
import { fetchFallbackStore, mapDtoToShopOffer } from '../api/client';
import {
  MapPin,
  X,
  Minimize2,
  ExternalLink,
  Copy,
  Check,
  Store,
  Navigation,
  ChevronLeft,
  Star,
  RefreshCw,
  FileQuestion,
  Receipt,
  PhoneCall,
  CheckSquare,
  Building,
} from 'lucide-react';

interface ShoppingCompanionModalProps {
  isOpen: boolean;
  onClose: () => void;
  onMinimize: () => void;
  offer: ShopOffer;
  product: Product;
  onSwitchOffer?: (newOffer: ShopOffer) => void;
}

export const ShoppingCompanionModal: React.FC<ShoppingCompanionModalProps> = ({
  isOpen,
  onClose,
  onMinimize,
  offer,
  product,
  onSwitchOffer,
}) => {
  const [currentStep, setCurrentStep] = useState<1 | 2 | 3 | 4>(1);
  const [copiedAddress, setCopiedAddress] = useState(false);
  const [invoiceNumber, setInvoiceNumber] = useState('');
  const [rating, setRating] = useState<number>(5);

  // Price discrepancy reporting state
  const [activeIssue, setActiveIssue] = useState<'closed' | 'price_mismatch' | 'contact' | null>(
    null
  );
  const [reportedPriceInput, setReportedPriceInput] = useState('');
  const [discrepancyReported, setDiscrepancyReported] = useState(false);
  const [fallbackData, setFallbackData] = useState<{
    bannerFa: string;
    offer: ShopOffer;
  } | null>(null);
  const [fallbackLoading, setFallbackLoading] = useState(false);

  const handleToggleClosedIssue = async () => {
    const next = activeIssue === 'closed' ? null : 'closed';
    setActiveIssue(next);
    if (next === 'closed' && !fallbackData) {
      setFallbackLoading(true);
      try {
        const res = await fetchFallbackStore(
          offer.id,
          offer.coordinates.lat,
          offer.coordinates.lng,
          [offer.shopId]
        );
        setFallbackData({
          bannerFa: res.banner_fa,
          offer: mapDtoToShopOffer(res.alternative_store),
        });
      } catch {
        setFallbackData(null);
      } finally {
        setFallbackLoading(false);
      }
    }
  };

  // Test Checklist State
  const [checkList, setCheckList] = useState({
    sealChecked: false,
    serialMatched: false,
    powerTested: false,
    warrantyChecked: false,
  });

  if (!isOpen) return null;

  const toggleCheck = (key: keyof typeof checkList) => {
    setCheckList((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  const checkedCount = Object.values(checkList).filter(Boolean).length;
  const checklistPercent = Math.round((checkedCount / 4) * 100);

  const handleCopy = () => {
    navigator.clipboard?.writeText(offer.address);
    setCopiedAddress(true);
    setTimeout(() => setCopiedAddress(false), 2000);
  };

  const openMap = (app: 'neshan' | 'balad' | 'google') => {
    const { lat, lng } = offer.coordinates;
    let url = '';
    if (app === 'neshan') {
      url = `https://nshn.ir/?lat=${lat}&lng=${lng}`;
    } else if (app === 'balad') {
      url = `https://balad.ir/location?latitude=${lat}&longitude=${lng}`;
    } else {
      url = `https://www.google.com/maps/dir/?api=1&destination=${lat},${lng}`;
    }
    window.open(url, '_blank');
  };

  const handleReportPriceMismatch = (e: React.FormEvent) => {
    e.preventDefault();
    setDiscrepancyReported(true);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-4 bg-black/85 backdrop-blur-md animate-fade-in font-sans select-none">
      <div className="relative w-full max-w-2xl bg-[#14141d] border border-[#2d2d3e] rounded-3xl shadow-2xl overflow-hidden flex flex-col max-h-[92vh]">
        {/* Top Header Bar */}
        <div className="p-4 sm:p-5 bg-gradient-to-r from-[#1b1722] via-[#161622] to-[#14141d] border-b border-[#242436] flex items-center justify-between gap-3">
          <div className="flex items-center gap-3 min-w-0">
            <div className="w-10 h-10 rounded-2xl bg-[#e9325a]/20 border border-[#e9325a]/40 flex items-center justify-center text-[#ff6688] shrink-0">
              <Navigation className="w-5 h-5 animate-pulse" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-black px-2 py-0.5 rounded-full bg-[#e9325a]/20 text-[#ff80a0] border border-[#e9325a]/30">
                  همراه خرید حضوری
                </span>
                <span className="text-xs text-neutral-400 truncate">
                  {offer.shopName}
                </span>
              </div>
              <h3 className="text-sm sm:text-base font-extrabold text-white truncate mt-0.5">
                {product.title}
              </h3>
            </div>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={onMinimize}
              className="p-2 rounded-xl text-neutral-400 hover:text-white hover:bg-[#20202e] transition-colors"
              title="کوچک کردن پنجره و ادامه در پس‌زمینه"
            >
              <Minimize2 className="w-4 h-4" />
            </button>
            <button
              onClick={onClose}
              className="p-2 rounded-xl text-neutral-400 hover:text-white hover:bg-[#20202e] transition-colors"
              title="بستن"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* 4-Step Progress Stepper: Realistic In-Person Journey */}
        <div className="px-4 py-3 bg-[#111118] border-b border-[#20202c]">
          <div className="grid grid-cols-4 gap-1.5 text-center">
            {[
              { num: 1, label: 'مسیریابی' },
              { num: 2, label: 'تست در مغازه' },
              { num: 3, label: 'پرداخت و فاکتور' },
              { num: 4, label: 'پایان خرید' },
            ].map((s) => {
              const isPast = currentStep > s.num;
              const isCurrent = currentStep === s.num;

              return (
                <button
                  key={s.num}
                  onClick={() => setCurrentStep(s.num as any)}
                  className={`py-2 px-1 rounded-xl text-xs font-bold transition-all flex flex-col items-center gap-1 ${
                    isCurrent
                      ? 'bg-[#e9325a] text-white shadow-md shadow-[#e9325a]/30'
                      : isPast
                      ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                      : 'bg-[#181822] text-neutral-500 hover:text-neutral-300'
                  }`}
                >
                  <div className="flex items-center gap-1">
                    {isPast ? (
                      <Check className="w-3 h-3 text-emerald-400" />
                    ) : (
                      <span className="text-[11px]">{s.num.toLocaleString('fa-IR')}</span>
                    )}
                    <span className="text-[11px] truncate">{s.label}</span>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* Step Body Content */}
        <div className="flex-1 overflow-y-auto p-4 sm:p-5 space-y-4 text-xs">
          {/* STEP 1: NAVIGATION & ARRIVAL */}
          {currentStep === 1 && (
            <div className="space-y-4 animate-fade-in">
              <div className="p-4 rounded-2xl bg-[#191924] border border-[#272738] space-y-3">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <MapPin className="w-4 h-4 text-[#ff4d79]" />
                    <span className="font-extrabold text-sm text-white">
                      مسیریابی به مقصد: {offer.shopName}
                    </span>
                  </div>
                  <span className="px-2.5 py-1 rounded-lg bg-amber-500/15 text-amber-300 font-bold border border-amber-500/30">
                    {offer.distanceKm.toLocaleString('fa-IR')} کیلومتر (حدود{' '}
                    {(offer.estimatedDrivingMins || 10).toLocaleString('fa-IR')} دقیقه)
                  </span>
                </div>

                <div className="p-3 rounded-xl bg-[#12121a] border border-[#222230] flex items-center justify-between gap-2">
                  <span className="text-neutral-300 leading-relaxed font-medium">
                    {offer.address}
                  </span>
                  <button
                    onClick={handleCopy}
                    className="px-2.5 py-1.5 rounded-lg bg-[#20202e] hover:bg-[#2b2b3e] text-neutral-300 flex items-center gap-1 shrink-0 transition-colors border border-[#2e2e42]"
                  >
                    {copiedAddress ? (
                      <span className="text-emerald-400 font-bold">کپی شد!</span>
                    ) : (
                      <>
                        <Copy className="w-3 h-3 text-neutral-400" />
                        <span>کپی آدرس</span>
                      </>
                    )}
                  </button>
                </div>

                {(offer.mallName || offer.mallFloor || offer.mallUnit) && (
                  <div className="flex flex-wrap items-center gap-1.5 pt-1">
                    {offer.mallName && (
                      <span className="px-2.5 py-1 rounded-lg bg-[#1d1d2b] border border-[#2f2f45] text-white font-bold flex items-center gap-1 text-[11px]">
                        <Building className="w-3.5 h-3.5 text-[#ff6688]" />
                        <span>{offer.mallName}</span>
                      </span>
                    )}
                    {offer.mallFloor && (
                      <span className="px-2.5 py-1 rounded-lg bg-[#271825] border border-[#e9325a]/40 text-[#ff80a0] font-bold text-[11px]">
                        {offer.mallFloor}
                      </span>
                    )}
                    {offer.mallUnit && (
                      <span className="px-2.5 py-1 rounded-lg bg-[#18252b] border border-sky-500/40 text-sky-300 font-bold text-[11px]">
                        {offer.mallUnit}
                      </span>
                    )}
                  </div>
                )}

                {offer.mallNote && (
                  <div className="text-[11px] text-neutral-400 flex items-center gap-1.5">
                    <span className="font-bold text-neutral-300">راهنمای داخل پاساژ:</span>
                    <span>{offer.mallNote}</span>
                  </div>
                )}

                {/* Direct Navigation Apps */}
                <div className="pt-2">
                  <span className="text-[11px] text-neutral-400 block mb-2 font-bold">
                    مسیریابی با نرم‌افزار گوشی:
                  </span>
                  <div className="grid grid-cols-3 gap-2">
                    <button
                      onClick={() => openMap('neshan')}
                      className="py-2.5 px-3 rounded-xl bg-[#1f1f2e] hover:bg-[#28283c] border border-[#2f2f45] text-neutral-200 font-bold flex items-center justify-center gap-1.5 transition-colors"
                    >
                      <Navigation className="w-3.5 h-3.5 text-blue-400" />
                      <span>نشان</span>
                    </button>
                    <button
                      onClick={() => openMap('balad')}
                      className="py-2.5 px-3 rounded-xl bg-[#1f1f2e] hover:bg-[#28283c] border border-[#2f2f45] text-neutral-200 font-bold flex items-center justify-center gap-1.5 transition-colors"
                    >
                      <Navigation className="w-3.5 h-3.5 text-emerald-400" />
                      <span>بلد</span>
                    </button>
                    <button
                      onClick={() => openMap('google')}
                      className="py-2.5 px-3 rounded-xl bg-[#1f1f2e] hover:bg-[#28283c] border border-[#2f2f45] text-neutral-200 font-bold flex items-center justify-center gap-1.5 transition-colors"
                    >
                      <ExternalLink className="w-3.5 h-3.5 text-amber-400" />
                      <span>گوگل‌مپ</span>
                    </button>
                  </div>
                </div>
              </div>

              <button
                onClick={() => setCurrentStep(2)}
                className="w-full py-3 rounded-2xl bg-[#e9325a] hover:bg-[#ff2d5f] text-white font-extrabold text-sm flex items-center justify-center gap-2 shadow-lg shadow-[#e9325a]/25 transition-all"
              >
                <span>رسیدم به فروشگاه (بررسی و تست کالا)</span>
                <ChevronLeft className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* STEP 2: IN-STORE INSPECTION CHECKLIST */}
          {currentStep === 2 && (
            <div className="space-y-4 animate-fade-in">
              <div className="p-4 rounded-2xl bg-[#191924] border border-[#272738] space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h4 className="font-extrabold text-sm text-white">
                      چک‌لیست تست کالا قبل از پرداخت در مغازه
                    </h4>
                    <p className="text-[11px] text-neutral-400 mt-0.5">
                      قبل از کارت کشیدن، این موارد را با حوصله در مغازه چک کنید:
                    </p>
                  </div>
                  <span
                    className={`px-2.5 py-1 rounded-xl text-xs font-black ${
                      checklistPercent === 100
                        ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                        : 'bg-[#20202e] text-neutral-300'
                    }`}
                  >
                    {checklistPercent}% تأیید
                  </span>
                </div>

                {/* Progress bar */}
                <div className="w-full bg-[#12121a] h-1.5 rounded-full overflow-hidden">
                  <div
                    className="bg-[#e9325a] h-full transition-all duration-300"
                    style={{ width: `${checklistPercent}%` }}
                  />
                </div>

                {/* Interactive Checkbox Items */}
                <div className="space-y-2 pt-1">
                  {[
                    {
                      key: 'sealChecked' as const,
                      title: 'پلمپ جعبه و برچسب کالا',
                      desc: 'برچسب و نوار پلمپ کارخانه مخدوش نباشد.',
                    },
                    {
                      key: 'serialMatched' as const,
                      title: 'تطبیق شماره سریال (Serial / IMEI)',
                      desc: 'شماره سریال درج‌شده روی جعبه با بدنه کالا و فاکتور یکی باشد.',
                    },
                    {
                      key: 'powerTested' as const,
                      title: 'روشن کردن و سلامت ظاهری',
                      desc: 'کالا را روشن کنید؛ بدنه بدون خط و شکستگی باشد.',
                    },
                    {
                      key: 'warrantyChecked' as const,
                      title: 'بررسی کارت گارانتی',
                      desc: `کارت گارانتی معتبر (${offer.warranty}) با مهر مغازه دریافت شود.`,
                    },
                  ].map((item) => (
                    <div
                      key={item.key}
                      onClick={() => toggleCheck(item.key)}
                      className={`p-3 rounded-xl border cursor-pointer transition-all flex items-start gap-3 ${
                        checkList[item.key]
                          ? 'bg-emerald-500/10 border-emerald-500/40 text-white'
                          : 'bg-[#151520] border-[#222232] text-neutral-300 hover:border-[#35354a]'
                      }`}
                    >
                      <div
                        className={`w-5 h-5 rounded-lg flex items-center justify-center shrink-0 mt-0.5 transition-colors ${
                          checkList[item.key]
                            ? 'bg-emerald-500 text-black'
                            : 'bg-[#222230] border border-[#353545]'
                        }`}
                      >
                        {checkList[item.key] && <Check className="w-3.5 h-3.5 stroke-[3]" />}
                      </div>
                      <div className="min-w-0">
                        <div className="font-bold text-xs">{item.title}</div>
                        <div className="text-[11px] text-neutral-400 mt-0.5 leading-relaxed">
                          {item.desc}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <button
                onClick={() => setCurrentStep(3)}
                className="w-full py-3 rounded-2xl bg-[#e9325a] hover:bg-[#ff2d5f] text-white font-extrabold text-sm flex items-center justify-center gap-2 shadow-lg shadow-[#e9325a]/25 transition-all"
              >
                <span>کالا تست شد، رفتن به مرحله پرداخت</span>
                <ChevronLeft className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* STEP 3: PAYMENT & RECEIVING INVOICE (No "پرداخت امن" online confusion) */}
          {currentStep === 3 && (
            <div className="space-y-4 animate-fade-in">
              <div className="p-4 rounded-2xl bg-[#191924] border border-[#272738] space-y-3.5">
                <div className="flex items-center justify-between">
                  <span className="font-extrabold text-sm text-white">
                    پرداخت در فروشگاه و دریافت فاکتور
                  </span>
                  <span className="text-sm font-black text-emerald-400">
                    {offer.price.toLocaleString('fa-IR')} تومان
                  </span>
                </div>

                <div className="p-3 rounded-xl bg-[#12121a] border border-[#222230] space-y-2 text-[11px]">
                  <div className="flex items-center gap-2 text-neutral-200">
                    <Receipt className="w-4 h-4 text-emerald-400 shrink-0" />
                    <span className="font-bold">نکات دریافت فاکتور در خرید حضوری:</span>
                  </div>
                  <ul className="list-disc list-inside space-y-1 text-neutral-400 pr-1 leading-relaxed">
                    <li>
                      روی برگه رسید کارتخوان بررسی کنید که نام پذیرنده به نام فروشگاه{' '}
                      <strong className="text-white">({offer.shopName})</strong> باشد.
                    </li>
                    <li>
                      حتماً فاکتور چاپی با مهر رسمی فروشگاه و درج مشخصات کالا دریافت نمایید.
                    </li>
                    <li>شماره سریال یا کد رجیستری دستگاه در فاکتور نوشته شود.</li>
                  </ul>
                </div>

                <div className="space-y-1.5">
                  <label className="text-[11px] font-bold text-neutral-300 block">
                    شماره فاکتور یا کد پیگیری کارتخوان (اختیاری):
                  </label>
                  <input
                    type="text"
                    value={invoiceNumber}
                    onChange={(e) => setInvoiceNumber(e.target.value)}
                    placeholder="مثال: ۸۴۹۲۳۱"
                    className="w-full bg-[#12121a] border border-[#282838] rounded-xl px-3 py-2 text-white text-xs focus:outline-none focus:border-[#e9325a]"
                  />
                </div>
              </div>

              <button
                onClick={() => setCurrentStep(4)}
                className="w-full py-3 rounded-2xl bg-[#e9325a] hover:bg-[#ff2d5f] text-white font-extrabold text-sm flex items-center justify-center gap-2 shadow-lg shadow-[#e9325a]/25 transition-all"
              >
                <span>پرداخت انجام شد و فاکتور گرفتم</span>
                <ChevronLeft className="w-4 h-4" />
              </button>
            </div>
          )}

          {/* STEP 4: COMPLETED & SATISFACTION */}
          {currentStep === 4 && (
            <div className="space-y-4 animate-fade-in text-center py-2">
              <div className="w-16 h-16 rounded-full bg-emerald-500/20 border-2 border-emerald-500/40 text-emerald-400 flex items-center justify-center mx-auto shadow-lg shadow-emerald-500/20">
                <CheckSquare className="w-8 h-8" />
              </div>

              <div className="space-y-1">
                <h4 className="text-base font-black text-white">
                  خرید شما انجام شد، مبارکتان باشد 🎉
                </h4>
                <p className="text-xs text-neutral-400 max-w-md mx-auto leading-relaxed">
                  اطلاعات خرید شما از {offer.shopName} ثبت شد. بازخورد شما به بهبود اطلاعات و
                  قیمت‌های ترب کمک می‌کند.
                </p>
              </div>

              {/* Star Rating for Shop */}
              <div className="p-4 rounded-2xl bg-[#191924] border border-[#272738] space-y-2 max-w-sm mx-auto">
                <span className="text-xs font-bold text-neutral-300 block">
                  تجربه مراجعه به {offer.shopName}:
                </span>
                <div className="flex items-center justify-center gap-1.5">
                  {[1, 2, 3, 4, 5].map((star) => (
                    <button
                      key={star}
                      onClick={() => setRating(star)}
                      className="p-1 transition-transform hover:scale-110"
                    >
                      <Star
                        className={`w-6 h-6 ${
                          star <= rating
                            ? 'text-amber-400 fill-amber-400'
                            : 'text-neutral-600'
                        }`}
                      />
                    </button>
                  ))}
                </div>
              </div>

              <button
                onClick={onClose}
                className="w-full py-3 rounded-2xl bg-emerald-500 hover:bg-emerald-600 text-black font-black text-sm transition-all shadow-lg shadow-emerald-500/20"
              >
                بستن همراه خرید
              </button>
            </div>
          )}

          {/* SIMPLIFIED RESCUE / REPORT SECTION */}
          <div className="pt-3 border-t border-[#20202c] space-y-2.5">
            <div className="flex items-center justify-between text-neutral-400 text-[11px] font-bold">
              <span>در صورت بروز مشکل در محل فروشگاه:</span>
            </div>

            <div className="grid grid-cols-3 gap-2">
              {/* Option 1: Price Mismatch Report */}
              <button
                onClick={() =>
                  setActiveIssue(activeIssue === 'price_mismatch' ? null : 'price_mismatch')
                }
                className={`p-2.5 rounded-xl border text-right transition-all ${
                  activeIssue === 'price_mismatch'
                    ? 'bg-[#291b22] border-[#e9325a] text-white'
                    : 'bg-[#181822] border-[#252536] text-neutral-300 hover:border-[#35354a]'
                }`}
              >
                <FileQuestion className="w-3.5 h-3.5 text-amber-400 mb-1" />
                <div className="font-bold text-[11px]">قیمت متفاوت بود؟</div>
                <div className="text-[10px] text-neutral-500">گزارش مغایرت قیمت</div>
              </button>

              {/* Option 2: Closed Shop */}
              <button
                onClick={handleToggleClosedIssue}
                className={`p-2.5 rounded-xl border text-right transition-all ${
                  activeIssue === 'closed'
                    ? 'bg-[#291b22] border-[#e9325a] text-white'
                    : 'bg-[#181822] border-[#252536] text-neutral-300 hover:border-[#35354a]'
                }`}
              >
                <Store className="w-3.5 h-3.5 text-[#ff4d79] mb-1" />
                <div className="font-bold text-[11px]">مغازه بسته بود؟</div>
                <div className="text-[10px] text-neutral-500">فروشگاه جایگزین باز</div>
              </button>

              {/* Option 3: Contact Store */}
              <button
                onClick={() =>
                  setActiveIssue(activeIssue === 'contact' ? null : 'contact')
                }
                className={`p-2.5 rounded-xl border text-right transition-all ${
                  activeIssue === 'contact'
                    ? 'bg-[#291b22] border-[#e9325a] text-white'
                    : 'bg-[#181822] border-[#252536] text-neutral-300 hover:border-[#35354a]'
                }`}
              >
                <PhoneCall className="w-3.5 h-3.5 text-emerald-400 mb-1" />
                <div className="font-bold text-[11px]">تماس با مغازه</div>
                <div className="text-[10px] text-neutral-500">{offer.phone}</div>
              </button>
            </div>

            {/* EXPANDED CONTENT: Price Discrepancy Reporting */}
            {activeIssue === 'price_mismatch' && (
              <div className="p-3.5 rounded-2xl bg-[#1e1915] border border-amber-500/40 space-y-2.5 animate-fade-in">
                <div className="flex items-center gap-1.5 font-bold text-amber-300">
                  <FileQuestion className="w-4 h-4 text-amber-400" />
                  <span>ثبت مغایرت قیمت فروشگاه:</span>
                </div>
                <p className="text-[11px] text-neutral-300 leading-relaxed">
                  اگر قیمت اعلام‌شده در فروشگاه با قیمت ثبت‌شده در سایت (
                  {offer.price.toLocaleString('fa-IR')} تومان) تفاوت داشت، آن را ثبت کنید تا تیم
                  پشتیبانی با فروشنده تماس گرفته و قیمت را اصلاح کند.
                </p>

                {discrepancyReported ? (
                  <div className="p-2.5 rounded-xl bg-emerald-500/15 border border-emerald-500/30 text-emerald-400 text-xs font-bold text-center">
                    ✓ گزارش شما ثبت شد. با صاحب فروشگاه تماس گرفته می‌شود تا قیمت در سایت تصحیح
                    گردد.
                  </div>
                ) : (
                  <form onSubmit={handleReportPriceMismatch} className="space-y-2">
                    <input
                      type="text"
                      required
                      value={reportedPriceInput}
                      onChange={(e) => setReportedPriceInput(e.target.value)}
                      placeholder="قیمت اعلامی فروشنده به تومان (مثلاً: ۴۲,۵۰۰,۰۰۰)"
                      className="w-full bg-[#12121a] border border-[#302720] rounded-xl px-3 py-2 text-white text-xs focus:outline-none focus:border-amber-400"
                    />
                    <button
                      type="submit"
                      className="w-full py-2 rounded-xl bg-amber-500 hover:bg-amber-600 text-black font-extrabold text-xs transition-colors"
                    >
                      ثبت گزارش برای پیگیری و اصلاح قیمت
                    </button>
                  </form>
                )}
              </div>
            )}

            {/* EXPANDED CONTENT: Closed / Alternative (`T027`) */}
            {activeIssue === 'closed' && (
              <div className="p-3.5 rounded-2xl bg-[#1f1620] border border-[#ff4d79]/40 space-y-2.5 animate-fade-in">
                <div className="flex items-center gap-1.5 font-bold text-[#ff80a0]">
                  <RefreshCw className={`w-3.5 h-3.5 ${fallbackLoading ? 'animate-spin' : ''}`} />
                  <span>
                    {fallbackData
                      ? fallbackData.bannerFa
                      : 'نزدیک‌ترین فروشگاه باز جایگزین:'}
                  </span>
                </div>
                {fallbackLoading ? (
                  <div className="text-xs text-neutral-300 py-1">
                    در حال جستجوی فروشگاه جایگزین باز در همان پاساژ یا خیابان...
                  </div>
                ) : fallbackData ? (
                  <div className="p-3 rounded-xl bg-[#14141d] border border-[#2b2b3d] space-y-2.5">
                    <div className="flex items-center justify-between gap-2">
                      <div>
                        <div className="font-extrabold text-white text-xs">
                          {fallbackData.offer.shopName}
                        </div>
                        <div className="text-[10px] text-neutral-400 mt-0.5">
                          {[
                            fallbackData.offer.mallName,
                            fallbackData.offer.mallFloor,
                            fallbackData.offer.mallUnit,
                          ]
                            .filter(Boolean)
                            .join(' • ') || fallbackData.offer.address}
                        </div>
                      </div>
                      <span className="font-black text-emerald-400 text-xs shrink-0">
                        {fallbackData.offer.price.toLocaleString('fa-IR')} تومان
                      </span>
                    </div>
                    {onSwitchOffer && (
                      <button
                        type="button"
                        onClick={() => {
                          onSwitchOffer(fallbackData.offer);
                          setActiveIssue(null);
                          setCurrentStep(1);
                        }}
                        className="w-full py-2 rounded-xl bg-[#e9325a] hover:bg-[#ff2d5f] text-white font-extrabold text-xs transition-colors cursor-pointer"
                      >
                        انتخاب و تغییر مسیر به این فروشگاه جایگزین
                      </button>
                    )}
                  </div>
                ) : (
                  <div className="p-2.5 rounded-xl bg-[#14141d] border border-[#2b2b3d] flex items-center justify-between">
                    <div>
                      <div className="font-bold text-white">فروشگاه تکنولند جمهوری</div>
                      <div className="text-[10px] text-neutral-400">
                        ۲ دقیقه پیاده · موجودی تاییدشده
                      </div>
                    </div>
                    <span className="font-black text-emerald-400">
                      {(offer.price + 200000).toLocaleString('fa-IR')} تومان
                    </span>
                  </div>
                )}
              </div>
            )}

            {/* EXPANDED CONTENT: Contact */}
            {activeIssue === 'contact' && (
              <div className="p-3.5 rounded-2xl bg-[#161c1a] border border-emerald-500/40 space-y-2 animate-fade-in">
                <div className="flex items-center justify-between">
                  <span className="text-white font-bold">شماره تلفن فروشگاه:</span>
                  <span className="text-emerald-400 font-extrabold">{offer.phone}</span>
                </div>
                <a
                  href={`tel:${offer.phone.replace(/[^0-9]/g, '')}`}
                  className="w-full py-2 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-black font-bold flex items-center justify-center gap-2 transition-all"
                >
                  <PhoneCall className="w-4 h-4" />
                  <span>تماس تلفنی با فروشگاه</span>
                </a>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};
