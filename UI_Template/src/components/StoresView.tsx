import React, { useState, useMemo, useEffect } from 'react';
import { ShopOffer, UserLocation, Product } from '../types';
import {
  MapPin,
  Clock,
  Store,
  PhoneCall,
  CheckCircle2,
  Building,
  Sparkles,
  Navigation,
  RefreshCw,
} from 'lucide-react';
import { InteractiveMap } from './InteractiveMap';
import { fetchFallbackStore, mapDtoToShopOffer } from '../api/client';

interface StoresViewProps {
  offers: ShopOffer[];
  selectedProduct: Product | null;
  userLocation: UserLocation;
  onOpenLocationPicker?: () => void;
  onStartVoiceCall: (offer: ShopOffer) => void;
  onStartShoppingTrip?: (offer: ShopOffer) => void;
  filterOpenOnly: boolean;
  filterTorobPay: boolean;
  filterInstallment: boolean;
}

export const StoresView: React.FC<StoresViewProps> = ({
  offers,
  selectedProduct,
  userLocation,
  onOpenLocationPicker,
  onStartVoiceCall,
  onStartShoppingTrip,
  filterOpenOnly,
  filterTorobPay,
  filterInstallment,
}) => {
  const [sortBy, setSortBy] = useState<'smart' | 'price' | 'distance'>('smart');
  const [selectedMall, setSelectedMall] = useState<string>('all');
  const [showBackupMap, setShowBackupMap] = useState<Record<string, boolean>>({});
  const [liveFallbacks, setLiveFallbacks] = useState<
    Record<string, { bannerFa: string; offer: ShopOffer } | 'loading'>
  >({});
  const [selectedOfferId, setSelectedOfferId] = useState<string | null>(null);

  useEffect(() => {
    setLiveFallbacks({});
    setShowBackupMap({});
  }, [userLocation.lat, userLocation.lng]);

  const toggleBackupOffer = async (offer: ShopOffer) => {
    const nextVisible = !showBackupMap[offer.id];
    setShowBackupMap((prev) => ({
      ...prev,
      [offer.id]: nextVisible,
    }));

    if (nextVisible && !liveFallbacks[offer.id]) {
      setLiveFallbacks((prev) => ({ ...prev, [offer.id]: 'loading' }));
      try {
        const res = await fetchFallbackStore(
          offer.id,
          userLocation.lat,
          userLocation.lng,
          [offer.shopId]
        );
        setLiveFallbacks((prev) => ({
          ...prev,
          [offer.id]: {
            bannerFa: res.banner_fa,
            offer: mapDtoToShopOffer(res.alternative_store),
          },
        }));
      } catch {
        const localAlt =
          offers.find((o) => o.id !== offer.id && o.isOpenNow) ||
          offers.find((o) => o.id !== offer.id);
        if (localAlt) {
          setLiveFallbacks((prev) => ({
            ...prev,
            [offer.id]: {
              bannerFa: `نزدیک‌ترین فروشگاه جایگزین (${localAlt.distanceKm.toLocaleString('fa-IR')} کیلومتر):`,
              offer: localAlt,
            },
          }));
        }
      }
    }
  };

  // Extract unique malls/clusters
  const malls = useMemo(() => {
    const set = new Set<string>();
    offers.forEach((o) => {
      if (o.mallName) set.add(o.mallName);
    });
    return Array.from(set);
  }, [offers]);

  // Filter and sort offers (if selectedProduct has exact matches in `offers`, filter by it; otherwise show all category offers)
  const filteredOffers = useMemo(() => {
    const hasExactProductOffers =
      selectedProduct && offers.some((o) => o.productId === selectedProduct.id);
    return offers
      .filter((o) => {
        if (hasExactProductOffers && selectedProduct && o.productId !== selectedProduct.id)
          return false;
        if (filterOpenOnly && !o.isOpenNow) return false;
        if (filterTorobPay && !o.torobPayAccepted) return false;
        if (filterInstallment && o.installmentOptions.length === 0) return false;
        if (selectedMall !== 'all' && o.mallName !== selectedMall) return false;
        return true;
      })
      .sort((a, b) => {
        if (sortBy === 'price') return a.price - b.price;
        if (sortBy === 'distance') return a.distanceKm - b.distanceKm;
        if (a.utilityScore !== undefined && b.utilityScore !== undefined) {
          return b.utilityScore - a.utilityScore;
        }
        const scoreA =
          a.price / 1000000 +
          a.distanceKm * 0.45 -
          (a.isOpenNow ? 2 : 0) -
          (a.torobPayAccepted ? 1 : 0);
        const scoreB =
          b.price / 1000000 +
          b.distanceKm * 0.45 -
          (b.isOpenNow ? 2 : 0) -
          (b.torobPayAccepted ? 1 : 0);
        return scoreA - scoreB;
      });
  }, [
    offers,
    selectedProduct,
    filterOpenOnly,
    filterTorobPay,
    filterInstallment,
    selectedMall,
    sortBy,
  ]);

  return (
    <div className="flex-1 overflow-y-auto p-4 md:p-6 bg-[#0c0c10] font-sans">
      <div className="max-w-4xl mx-auto space-y-5">
        {/* Top Filter & Sort Bar */}
        <div className="p-4 rounded-2xl bg-[#13131a] border border-[#1f1f2a] flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <Store className="w-5 h-5 text-[#e9325a]" />
              <h2 className="text-base md:text-lg font-extrabold text-white">
                فروشگاه‌های حضوری تهران{' '}
                {selectedProduct ? `(${selectedProduct.title})` : ''}
              </h2>
            </div>
            <p className="text-[13px] sm:text-sm text-neutral-400 mt-1 leading-relaxed">
              مقایسه هوشمند قیمت حضوری، مسافت، طبقه/واحد پاساژ و شرایط اقساطی از مبدا{' '}
              <button
                type="button"
                onClick={onOpenLocationPicker}
                className="text-[#ff7597] hover:underline font-bold cursor-pointer"
                title="تغییر موقعیت مبدأ روی نقشه"
              >
                {userLocation.name} (تغییر موقعیت)
              </button>
            </p>
          </div>

          {/* Sort Tabs */}
          <div className="flex items-center gap-1.5 bg-[#0c0c10] p-1 rounded-xl border border-[#22222d]">
            {[
              { id: 'smart', label: 'امتیاز هوشمند ترب‌چیت' },
              { id: 'price', label: 'کمترین قیمت' },
              { id: 'distance', label: 'نزدیک‌ترین' },
            ].map((tab) => (
              <button
                key={tab.id}
                onClick={() => setSortBy(tab.id as 'smart' | 'price' | 'distance')}
                className={`px-3 py-1.5 rounded-lg text-[13px] sm:text-sm font-bold transition-all ${
                  sortBy === tab.id
                    ? 'bg-[#e9325a] text-white'
                    : 'text-neutral-400 hover:text-white'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Interactive Dark-Mode Tehran Leaflet Map (`T021`) */}
        <InteractiveMap
          offers={filteredOffers.length > 0 ? filteredOffers : offers}
          userLocation={userLocation}
          selectedOfferId={selectedOfferId}
          onSelectOffer={(offer) => setSelectedOfferId(offer.id)}
          onStartShoppingTrip={onStartShoppingTrip}
          onChangeLocation={onOpenLocationPicker}
        />

        {/* Mall / Cluster Quick Chips */}
        {malls.length > 0 && (
          <div className="flex items-center gap-2 overflow-x-auto pb-1">
            <span className="text-[13px] sm:text-sm text-neutral-400 shrink-0 flex items-center gap-1.5">
              <Building className="w-4 h-4 text-[#ff6688]" />
              بورس و پاساژها:
            </span>
            <button
              onClick={() => setSelectedMall('all')}
              className={`px-3 py-1.5 rounded-xl text-[13px] sm:text-sm font-semibold shrink-0 border transition-colors ${
                selectedMall === 'all'
                  ? 'bg-[#e9325a]/15 border-[#e9325a] text-[#ff4d79]'
                  : 'bg-[#14141c] border-[#22222d] text-neutral-400 hover:text-white'
              }`}
            >
              همه مراکز خرید ({offers.length.toLocaleString('fa-IR')})
            </button>
            {malls.map((mall) => (
              <button
                key={mall}
                onClick={() => setSelectedMall(mall)}
                className={`px-3 py-1.5 rounded-xl text-[13px] sm:text-sm font-semibold shrink-0 border transition-colors ${
                  selectedMall === mall
                    ? 'bg-[#e9325a]/15 border-[#e9325a] text-[#ff4d79]'
                    : 'bg-[#14141c] border-[#22222d] text-neutral-400 hover:text-white'
                }`}
              >
                {mall}
              </button>
            ))}
          </div>
        )}

        {/* Store Offers List */}
        {filteredOffers.length === 0 ? (
          <div className="p-12 rounded-2xl bg-[#13131a] border border-[#1f1f2a] text-center space-y-2">
            <p className="text-base font-bold text-neutral-300">
              فروشگاهی با این فیلترها یافت نشد.
            </p>
            <p className="text-[13px] sm:text-sm text-neutral-500">
              فیلترهای سایدبار یا پاساژ انتخابی را تغییر دهید.
            </p>
          </div>
        ) : (
          <div className="space-y-3.5">
            {filteredOffers.map((offer, index) => {
              const fallbackEntry = liveFallbacks[offer.id];
              return (
                <div
                  key={offer.id}
                  onClick={() => setSelectedOfferId(offer.id)}
                  className={`p-4 md:p-5 rounded-2xl transition-all border ${
                    index === 0 && sortBy === 'smart'
                      ? 'torob-gradient-border bg-[#14141d]'
                      : selectedOfferId === offer.id
                        ? 'bg-[#171723] border-[#e9325a]'
                        : 'bg-[#13131a] border-[#20202c] hover:border-[#2e2e40]'
                  }`}
                >
                  {/* Top Badge Row (Pareto Role + Utility Score) */}
                  <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      {(offer.paretoBadge || (index === 0 && sortBy === 'smart')) && (
                        <span className="inline-flex items-center gap-1.5 text-xs sm:text-[13px] font-bold text-[#ff4d79] bg-[#e9325a]/15 px-2.5 py-1 rounded-lg border border-[#e9325a]/30">
                          <Sparkles className="w-3.5 h-3.5" />
                          <span>
                            {offer.paretoBadge ||
                              'بهترین توازن قیمت و مسافت برای مراجعه حضوری'}
                          </span>
                        </span>
                      )}
                      {offer.utilityScore !== undefined && (
                        <span className="text-xs sm:text-[13px] font-extrabold text-emerald-300 bg-emerald-500/15 border border-emerald-500/30 px-2.5 py-1 rounded-lg">
                          امتیاز مطلوبیت: {offer.utilityScore.toLocaleString('fa-IR')}٪
                        </span>
                      )}
                    </div>
                    <span className="text-xs sm:text-[13px] text-neutral-400">
                      امتیاز عملکرد در ترب:{' '}
                      <strong className="text-white">
                        {offer.reputationScore.toLocaleString('fa-IR')} از ۵
                      </strong>
                    </span>
                  </div>

                  <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                    {/* Right Info */}
                    <div className="space-y-2.5 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <h3 className="text-base md:text-lg font-extrabold text-white">
                          {offer.shopName}
                        </h3>

                        {offer.isRealShop && (
                          <span className="text-xs px-2.5 py-0.5 rounded-md bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-bold">
                            فروشگاه رسمی تاییدشده در ترب
                          </span>
                        )}

                        <span
                          className={`text-xs px-2.5 py-0.5 rounded-md font-semibold ${
                            offer.isOpenNow
                              ? 'bg-emerald-500/10 text-emerald-400'
                              : 'bg-neutral-800 text-neutral-400'
                          }`}
                        >
                          {offer.isOpenNow
                            ? `باز است (${offer.workingHours})`
                            : `بسته (${offer.workingHours})`}
                        </span>
                      </div>

                      {/* Indoor Mall Micro-Navigation (`پاساژ / طبقه / واحد`) & Address (`T022`) */}
                      <div className="flex flex-wrap items-center gap-2 text-[13px] sm:text-sm text-neutral-300 leading-relaxed">
                        {offer.mallName && (
                          <span className="px-2.5 py-0.5 rounded-lg bg-[#1d1d28] border border-[#2c2c3c] text-white font-semibold flex items-center gap-1.5">
                            <Building className="w-3.5 h-3.5 text-[#ff6688]" />
                            <span>{offer.mallName}</span>
                          </span>
                        )}
                        {offer.mallFloor && (
                          <span className="px-2.5 py-0.5 rounded-lg bg-[#251824] border border-[#e9325a]/40 text-[#ff80a0] font-bold text-xs sm:text-[13px]">
                            {offer.mallFloor}
                          </span>
                        )}
                        {offer.mallUnit && (
                          <span className="px-2.5 py-0.5 rounded-lg bg-[#1b2428] border border-sky-500/30 text-sky-300 font-bold text-xs sm:text-[13px]">
                            {offer.mallUnit}
                          </span>
                        )}
                        <span>{offer.address}</span>
                      </div>

                      {/* Why This Shop Attribution Chips */}
                      {offer.whyThisShop && offer.whyThisShop.length > 0 && (
                        <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
                          {offer.whyThisShop.map((reason, rIdx) => (
                            <span
                              key={rIdx}
                              className="text-xs px-2.5 py-0.5 rounded-md bg-[#191926] border border-[#2b2b3d] text-neutral-300"
                            >
                              ✦ {reason}
                            </span>
                          ))}
                        </div>
                      )}

                      {/* Distance, Freshness & Payment Options */}
                      <div className="flex flex-wrap items-center gap-3 text-xs sm:text-[13px] text-neutral-400 pt-1">
                        <span className="flex items-center gap-1 text-amber-300 font-semibold">
                          <MapPin className="w-4 h-4" />
                          {offer.distanceKm.toLocaleString('fa-IR')} کیلومتر فاصله (~
                          {offer.estimatedDrivingMins.toLocaleString('fa-IR')} دقیقه با خودرو)
                        </span>

                        <span className="flex items-center gap-1">
                          <Clock className="w-4 h-4" />
                          بروزرسانی قیمت: {offer.lastUpdated}
                        </span>

                        {offer.torobPayAccepted && (
                          <span className="flex items-center gap-1 text-[#ff4d79] font-bold">
                            <CheckCircle2 className="w-4 h-4" />
                            ترب‌پی حضوری فعال
                          </span>
                        )}

                        {offer.installmentOptions.length > 0 && (
                          <span className="text-neutral-300">
                            اقساط: {offer.installmentOptions.join(' ، ')}
                          </span>
                        )}
                      </div>
                    </div>

                    {/* Left Price & Actions */}
                    <div className="flex sm:flex-row md:flex-col items-start sm:items-center md:items-end justify-between gap-3 pt-3 md:pt-0 border-t md:border-t-0 border-[#20202b]">
                      <div className="text-right md:text-left">
                        <div className="text-xs text-neutral-400">قیمت خرید حضوری:</div>
                        <div className="text-lg md:text-xl font-black text-white">
                          {offer.price.toLocaleString('fa-IR')}{' '}
                          <span className="text-[13px] font-normal text-neutral-400">تومان</span>
                        </div>
                        <div className="text-xs text-emerald-400 mt-0.5">{offer.warranty}</div>
                      </div>

                      <div className="flex items-center gap-2 w-full sm:w-auto">
                        {onStartShoppingTrip && (
                          <button
                            onClick={() => onStartShoppingTrip(offer)}
                            className="flex-1 sm:flex-initial px-4 py-2 rounded-xl bg-gradient-to-r from-[#e9325a] to-[#ff4d79] hover:opacity-90 text-white text-[13px] sm:text-sm font-bold flex items-center justify-center gap-1.5 shadow-lg shadow-[#e9325a]/25 transition-all cursor-pointer"
                          >
                            <Navigation className="w-4 h-4" />
                            <span>همراهی گام‌به‌گام خرید</span>
                          </button>
                        )}

                        <button
                          onClick={() => onStartVoiceCall(offer)}
                          className="px-3.5 py-2 rounded-xl bg-[#1f1f2e] hover:bg-[#2a2a3d] text-neutral-200 border border-[#34344a] text-[13px] sm:text-sm font-bold flex items-center justify-center gap-1.5 transition-colors cursor-pointer"
                          title="تماس با فروشگاه"
                        >
                          <PhoneCall className="w-4 h-4 text-[#ff80a0]" />
                          <span>اطلاعات تماس</span>
                        </button>
                      </div>
                    </div>
                  </div>

                  {/* Expandable Live 1-Tap Backup Store Rescue (`T023`) */}
                  <div className="mt-3 pt-2.5 border-t border-[#1e1e2a]">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleBackupOffer(offer);
                      }}
                      className="text-xs sm:text-[13px] font-bold text-amber-400/90 hover:text-amber-300 flex items-center gap-1.5 transition-colors cursor-pointer"
                    >
                      <span>⚡</span>
                      <span>
                        {showBackupMap[offer.id]
                          ? 'بستن پیشنهاد جایگزین فوری'
                          : 'اگر مغازه بسته بود یا موجودی نداشت، فروشگاه جایگزین فوری چی داریم؟'}
                      </span>
                    </button>

                    {showBackupMap[offer.id] && (
                      <div
                        onClick={(e) => e.stopPropagation()}
                        className="mt-2 p-3.5 rounded-xl bg-[#181824] border border-amber-500/30 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-[13px] sm:text-sm animate-fade-in"
                      >
                        {fallbackEntry === 'loading' ? (
                          <div className="flex items-center gap-2 text-amber-300">
                            <RefreshCw className="w-4 h-4 animate-spin" />
                            <span>در حال یافتن نزدیک‌ترین فروشگاه باز جایگزین در همان محدوده...</span>
                          </div>
                        ) : fallbackEntry ? (
                          <>
                            <div className="space-y-1">
                              <span className="font-bold text-amber-300 block">
                                {fallbackEntry.bannerFa}
                              </span>
                              <span className="text-neutral-200 font-extrabold text-sm sm:text-base block">
                                {fallbackEntry.offer.shopName}{' '}
                                {fallbackEntry.offer.mallName
                                  ? `(${[
                                      fallbackEntry.offer.mallName,
                                      fallbackEntry.offer.mallFloor,
                                      fallbackEntry.offer.mallUnit,
                                    ]
                                      .filter(Boolean)
                                      .join(' • ')})`
                                  : ''}
                              </span>
                              <span className="text-xs sm:text-[13px] text-neutral-400 block">
                                قیمت حضوری:{' '}
                                <strong className="text-white">
                                  {fallbackEntry.offer.price.toLocaleString('fa-IR')} تومان
                                </strong>{' '}
                                • وضعیت:{' '}
                                <strong className="text-emerald-400">
                                  {fallbackEntry.offer.isOpenNow ? 'هم‌اکنون باز' : 'ثبت‌شده'}
                                </strong>
                              </span>
                            </div>
                            <div className="flex items-center gap-2 shrink-0">
                              {onStartShoppingTrip && (
                                <button
                                  onClick={() => onStartShoppingTrip(fallbackEntry.offer)}
                                  className="px-3.5 py-2 rounded-xl bg-amber-500 hover:bg-amber-400 text-black font-extrabold text-xs sm:text-[13px] transition-colors cursor-pointer"
                                >
                                  همراهی به فروشگاه جایگزین
                                </button>
                              )}
                              <button
                                onClick={() => onStartVoiceCall(fallbackEntry.offer)}
                                className="px-3 py-2 rounded-xl bg-[#252536] hover:bg-[#303046] text-white font-bold text-xs sm:text-[13px] transition-colors cursor-pointer"
                              >
                                تماس فوری
                              </button>
                            </div>
                          </>
                        ) : (
                          <span className="text-neutral-400">
                            فروشگاه جایگزین دیگری در این شعاع یافت نشد.
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};
