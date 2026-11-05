import React, { useState } from 'react';
import { ShopOffer, UserLocation, Product } from '../types';
import { USER_LOCATIONS } from '../data/mockData';
import {
  MapPin,
  Clock,
  PhoneCall,
  CreditCard,
  Compass,
  ShieldCheck,
  ChevronDown,
  Copy,
  Check,
  Navigation,
} from 'lucide-react';

interface StoresViewProps {
  offers: ShopOffer[];
  userLocation: UserLocation;
  setUserLocation: (loc: UserLocation) => void;
  selectedProduct: Product;
  onStartVoiceCall: (offer: ShopOffer) => void;
  onStartShoppingTrip: (offer: ShopOffer) => void;
  filterOpenOnly: boolean;
  filterTorobPay: boolean;
  filterInstallment: boolean;
}

export const StoresView: React.FC<StoresViewProps> = ({
  offers,
  userLocation,
  setUserLocation,
  selectedProduct,
  onStartVoiceCall,
  onStartShoppingTrip,
  filterOpenOnly,
  filterTorobPay,
  filterInstallment,
}) => {
  const [expandedOfferId, setExpandedOfferId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const [showBackupFor, setShowBackupFor] = useState<string | null>(null);

  // Filter offers based on active settings (without restrictive mall tags)
  const filteredOffers = offers.filter((offer) => {
    if (filterOpenOnly && !offer.isOpenNow) return false;
    if (filterTorobPay && !offer.torobPayAccepted) return false;
    if (filterInstallment && offer.installmentOptions.length === 0) return false;
    return true;
  });

  const handleCopyAddress = (id: string, address: string) => {
    navigator.clipboard?.writeText(address);
    setCopiedId(id);
    setTimeout(() => {
      setCopiedId(null);
    }, 2000);
  };

  const toggleExpand = (id: string) => {
    setExpandedOfferId((prev) => (prev === id ? null : id));
  };

  return (
    <div className="flex-1 overflow-y-auto p-4 md:p-6 bg-[#0c0c10] space-y-4 font-sans select-none">
      <div className="max-w-4xl mx-auto space-y-4">
        {/* Compact Product Banner */}
        <div className="p-3.5 md:p-4 rounded-2xl bg-[#14141a] border border-[#24242e] flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <div className="w-12 h-12 rounded-xl overflow-hidden bg-black border border-[#282834] shrink-0">
              <img
                src={selectedProduct.image}
                alt={selectedProduct.title}
                className="w-full h-full object-cover"
              />
            </div>
            <div>
              <h2 className="text-sm font-black text-white leading-tight">
                {selectedProduct.title}
              </h2>
              <div className="text-xs text-neutral-400 flex items-center gap-2 mt-1 flex-wrap">
                <span>کف قیمت تهران:</span>
                <span className="text-emerald-400 font-black">
                  {selectedProduct.minPrice.toLocaleString('fa-IR')} تومان
                </span>
                <span>·</span>
                <div className="flex items-center gap-1 text-neutral-300">
                  <MapPin className="w-3.5 h-3.5 text-[#e9325a]" />
                  <span>محله شما:</span>
                  <select
                    value={userLocation.id}
                    onChange={(e) => {
                      const loc = USER_LOCATIONS.find((l) => l.id === e.target.value);
                      if (loc) setUserLocation(loc);
                    }}
                    className="bg-[#1c1c24] text-white text-xs px-2 py-0.5 rounded-lg border border-[#2b2b36] focus:outline-none cursor-pointer"
                  >
                    {USER_LOCATIONS.map((loc) => (
                      <option key={loc.id} value={loc.id} className="bg-[#14141a]">
                        {loc.name}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </div>
          </div>

          <div className="text-left sm:text-right shrink-0">
            <span className="text-xs font-bold text-neutral-300">
              {filteredOffers.length} فروشگاه حضوری فعال
            </span>
          </div>
        </div>

        {/* Streamlined Store Cards */}
        <div className="space-y-3">
          {filteredOffers.length === 0 ? (
            <div className="text-center py-10 p-4 bg-[#14141a] rounded-2xl border border-[#202028] text-neutral-400 text-xs">
              فروشگاهی با فیلترهای انتخابی شما یافت نشد.
            </div>
          ) : (
            filteredOffers.map((offer, index) => {
              const isExpanded = expandedOfferId === offer.id;
              const isBackupOpen = showBackupFor === offer.id;

              return (
                <div
                  key={offer.id}
                  className={`rounded-2xl bg-[#14141a] border transition-all duration-200 ${
                    isExpanded
                      ? 'border-[#e9325a]/70 shadow-lg shadow-[#e9325a]/10 bg-[#161620]'
                      : 'border-[#22222c] hover:border-[#353545]'
                  }`}
                >
                  {/* Clean, Scannable Primary Card Row */}
                  <div className="p-4 flex flex-col md:flex-row md:items-center justify-between gap-3.5">
                    {/* Right side: Rank + Store Name + Mall/Neighborhood & Distance */}
                    <div className="flex items-center gap-3 min-w-0">
                      <span className="w-7 h-7 rounded-lg bg-[#1f1f2a] text-neutral-300 font-black text-xs flex items-center justify-center shrink-0 border border-[#2e2e3d]">
                        {(index + 1).toLocaleString('fa-IR')}
                      </span>

                      <div className="min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <h3 className="text-sm font-extrabold text-white truncate">
                            {offer.shopName}
                          </h3>
                          {offer.isRealShop && (
                            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-md bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 shrink-0">
                              رسمی
                            </span>
                          )}
                          {offer.torobPayAccepted && (
                            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-md bg-[#e9325a]/15 text-[#ff6688] border border-[#e9325a]/30 shrink-0">
                              ترب‌پی
                            </span>
                          )}
                        </div>

                        {/* Summary Location Line: No Floor, Clean Persian Typography for Distance */}
                        <div className="flex items-center gap-2 text-xs text-neutral-400 mt-1 flex-wrap">
                          <span className="text-neutral-200 font-medium">
                            {offer.mallName || offer.neighborhood}
                          </span>
                          <span>·</span>
                          <span className="text-amber-300 font-bold">
                            {offer.distanceKm.toLocaleString('fa-IR')} کیلومتر
                          </span>
                          <span>·</span>
                          <span
                            className={`text-[11px] font-semibold ${
                              offer.isOpenNow ? 'text-emerald-400' : 'text-neutral-500'
                            }`}
                          >
                            {offer.isOpenNow ? 'باز است' : 'بسته'}
                          </span>
                        </div>
                      </div>
                    </div>

                    {/* Left side: Price & Action Buttons */}
                    <div className="flex items-center justify-between md:justify-end gap-3 pt-2 md:pt-0 border-t md:border-t-0 border-[#1f1f28] shrink-0">
                      <div className="text-right">
                        <span className="text-[10px] text-neutral-500 block leading-tight">
                          قیمت حضوری
                        </span>
                        <span className="text-base font-black text-white">
                          {offer.price.toLocaleString('fa-IR')}
                          <span className="text-xs font-normal text-neutral-400 mr-1">
                            تومان
                          </span>
                        </span>
                      </div>

                      <div className="flex items-center gap-1.5">
                        {/* Live Shopping Companion Button */}
                        <button
                          onClick={() => onStartShoppingTrip(offer)}
                          className="px-3 py-2 rounded-xl bg-gradient-to-r from-[#e9325a] to-[#ff4d79] hover:opacity-90 text-white text-xs font-black flex items-center gap-1.5 shadow-md shadow-[#e9325a]/25 hover:scale-[1.02] active:scale-95 transition-all"
                          title="همراهی هوشمند در طول مسیر، تست کالا در مغازه و پرداخت امن"
                        >
                          <Navigation className="w-3.5 h-3.5" />
                          <span>همراهی خرید</span>
                        </button>

                        {/* Details & Address Toggle Button */}
                        <button
                          onClick={() => toggleExpand(offer.id)}
                          className={`px-2.5 py-2 rounded-xl text-xs font-bold flex items-center gap-1 transition-all ${
                            isExpanded
                              ? 'bg-[#242432] text-white border border-[#3b3b4f]'
                              : 'bg-[#1b1b24] text-neutral-300 hover:text-white hover:bg-[#22222e] border border-[#282836]'
                          }`}
                        >
                          <MapPin className="w-3.5 h-3.5 text-[#ff6688]" />
                          <span className="hidden sm:inline">
                            {isExpanded ? 'بستن' : 'آدرس'}
                          </span>
                          <ChevronDown
                            className={`w-3.5 h-3.5 transition-transform duration-200 ${
                              isExpanded ? 'rotate-180 text-white' : 'text-neutral-400'
                            }`}
                          />
                        </button>

                        {/* Contact Store CTA */}
                        <button
                          onClick={() => onStartVoiceCall(offer)}
                          className="p-2 sm:px-3 sm:py-2 rounded-xl bg-[#20202c] hover:bg-[#2a2a3b] text-neutral-200 hover:text-white border border-[#2f2f42] text-xs font-bold flex items-center gap-1.5 transition-all"
                          title="اطلاعات و تماس مستقیم با فروشگاه"
                        >
                          <PhoneCall className="w-3.5 h-3.5 text-[#ff80a0]" />
                          <span className="hidden sm:inline">تماس با فروشگاه</span>
                          <span className="sm:hidden">تماس</span>
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Expandable Details Section (revealed only upon request) */}
                  {isExpanded && (
                    <div className="px-4 pb-4 pt-3 border-t border-[#22222e] space-y-3.5 bg-[#121218]/60 rounded-b-2xl animate-fade-in">
                      {/* Address & Navigation Card (No Floor) */}
                      <div className="p-3.5 rounded-xl bg-[#181822] border border-[#282836] space-y-2">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-start gap-2 text-xs">
                            <MapPin className="w-4 h-4 text-[#ff4d79] shrink-0 mt-0.5" />
                            <div>
                              <div className="font-bold text-white leading-relaxed">
                                {offer.address}
                              </div>
                              <div className="text-neutral-400 text-[11px] mt-1 flex items-center gap-2">
                                <span>محدوده:</span>
                                <span className="text-neutral-200 font-medium">
                                  {offer.mallName || offer.neighborhood}
                                </span>
                              </div>
                            </div>
                          </div>

                          <button
                            onClick={() => handleCopyAddress(offer.id, offer.address)}
                            className="px-2.5 py-1.5 rounded-lg bg-[#222230] hover:bg-[#2d2d40] text-[11px] text-neutral-300 flex items-center gap-1.5 shrink-0 transition-colors border border-[#303042]"
                            title="کپی آدرس برای نشان و بلد"
                          >
                            {copiedId === offer.id ? (
                              <>
                                <Check className="w-3 h-3 text-emerald-400" />
                                <span className="text-emerald-400 font-bold">کپی شد!</span>
                              </>
                            ) : (
                              <>
                                <Copy className="w-3 h-3 text-neutral-400" />
                                <span>کپی آدرس</span>
                              </>
                            )}
                          </button>
                        </div>

                        {/* Walking Guidance / Location Note if available */}
                        {offer.mallNote && (
                          <div className="pt-2 border-t border-[#242432] flex items-start gap-2 text-xs text-neutral-300">
                            <Compass className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
                            <div className="leading-relaxed">
                              <span className="font-bold text-neutral-200">
                                راهنمای دسترسی:{' '}
                              </span>
                              <span className="text-neutral-300">{offer.mallNote}</span>
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Store Meta Badges Grid */}
                      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                        <div className="p-2.5 rounded-xl bg-[#181822] border border-[#252534]">
                          <span className="text-[10px] text-neutral-400 block flex items-center gap-1">
                            <Clock className="w-3 h-3 text-neutral-400" />
                            ساعات کاری
                          </span>
                          <span className="font-bold text-white text-[11px] mt-0.5 block truncate">
                            {offer.workingHours}
                          </span>
                        </div>

                        <div className="p-2.5 rounded-xl bg-[#181822] border border-[#252534]">
                          <span className="text-[10px] text-neutral-400 block flex items-center gap-1">
                            <ShieldCheck className="w-3 h-3 text-emerald-400" />
                            گارانتی
                          </span>
                          <span className="font-bold text-white text-[11px] mt-0.5 block truncate">
                            {offer.warranty}
                          </span>
                        </div>

                        <div className="p-2.5 rounded-xl bg-[#181822] border border-[#252534]">
                          <span className="text-[10px] text-neutral-400 block flex items-center gap-1">
                            <CreditCard className="w-3 h-3 text-[#ff4d79]" />
                            شرایط اقساط
                          </span>
                          <span className="font-bold text-white text-[11px] mt-0.5 block truncate">
                            {offer.installmentOptions.length > 0
                              ? offer.installmentOptions.join('، ')
                              : 'فقط نقدی'}
                          </span>
                        </div>

                        <div className="p-2.5 rounded-xl bg-[#181822] border border-[#252534]">
                          <span className="text-[10px] text-neutral-400 block flex items-center gap-1">
                            <Clock className="w-3 h-3 text-neutral-400" />
                            به‌روزرسانی
                          </span>
                          <span className="font-bold text-white text-[11px] mt-0.5 block truncate">
                            {offer.lastUpdated}
                          </span>
                        </div>
                      </div>

                      {/* Emergency Backup Shop Drawer */}
                      <div className="pt-1">
                        <button
                          onClick={() => setShowBackupFor(isBackupOpen ? null : offer.id)}
                          className="text-[11px] text-neutral-400 hover:text-[#ff80a0] flex items-center gap-1.5 transition-colors"
                        >
                          <Navigation className="w-3 h-3 text-[#ff4d79]" />
                          <span>
                            {isBackupOpen
                              ? 'بستن فروشگاه جایگزین'
                              : 'اگر مغازه بسته بود، فروشگاه جایگزین در ۵۰ متری چی داریم؟'}
                          </span>
                        </button>

                        {isBackupOpen && (
                          <div className="mt-2 p-3 rounded-xl bg-[#1b1720] border border-[#ff4d79]/30 text-xs flex items-center justify-between gap-3 animate-fade-in">
                            <div>
                              <div className="font-bold text-white">فروشگاه تکنولند جمهوری</div>
                              <div className="text-[11px] text-neutral-400 mt-0.5">
                                در همان محدوده (۲ دقیقه پیاده)
                              </div>
                            </div>
                            <span className="text-xs font-bold text-emerald-400 shrink-0">
                              {(offer.price + 200000).toLocaleString('fa-IR')} تومان
                            </span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </div>
  );
};
