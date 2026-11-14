import React, { useState, useRef, useEffect } from 'react';
import { ChatMessage, Product, ShopOffer, UserLocation } from '../types';
import {
  SendHorizontal,
  PhoneCall,
  Store,
  ChevronLeft,
  ChevronDown,
  ExternalLink,
  Clock,
  MapPin,
  CheckCircle2,
  Building,
  ThumbsUp,
  ThumbsDown,
  Swords,
} from 'lucide-react';
import { TorobLogo } from './TorobLogo';
import { MarkdownRenderer } from './MarkdownRenderer';
import { SearchingPapersAnimation } from './SearchingPapersAnimation';
import { FeatureClarificationCard } from './FeatureClarificationCard';
import { InteractiveMap } from './InteractiveMap';

interface ChatViewProps {
  messages: ChatMessage[];
  onSendMessage: (text: string) => void;
  isLoading: boolean;
  userLocation: UserLocation;
  onOpenLocationPicker?: () => void;
  onSelectProduct: (product: Product) => void;
  onStartVoiceCall: (offer: ShopOffer) => void;
  onStartShoppingTrip?: (offer: ShopOffer) => void;
  onNavigateToStores: () => void;
  onSubmitFeatureClarification?: (messageId: string, answers: Record<string, string>) => void;
  onFeedback?: (messageId: string, feedbackType: 'thumbs_up' | 'thumbs_down') => void;
}

export const ChatView: React.FC<ChatViewProps> = ({
  messages,
  onSendMessage,
  isLoading,
  userLocation,
  onOpenLocationPicker,
  onSelectProduct,
  onStartVoiceCall,
  onStartShoppingTrip,
  onNavigateToStores,
  onSubmitFeatureClarification,
  onFeedback,
}) => {
  const [inputText, setInputText] = useState('');
  const [feedbackMap, setFeedbackMap] = useState<Record<string, 'like' | 'dislike'>>({});
  const [expandedShopOffers, setExpandedShopOffers] = useState<Record<string, boolean>>({});
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const toggleShopOffers = (messageId: string) => {
    setExpandedShopOffers((prev) => ({
      ...prev,
      [messageId]: !prev[messageId],
    }));
  };

  // Spark only runs on the initial landing screen before chat starts
  const isInitialScreen = messages.length === 0;

  // Active question form check: disables bottom input until user submits answers
  const isQuestionFormActive = messages.some(
    (m) => m.featureClarification && !m.featureClarification.isSubmitted
  );

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages, isLoading]);

  const handleSend = (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    if (!inputText.trim() || isLoading || isQuestionFormActive) return;
    const text = inputText;
    setInputText('');
    onSendMessage(text);
  };

  const samplePills = [
    'بهترین گوشی برای عکاسی',
    'من یک اسکوتر برقی مناسب می‌خوام',
    'لپ‌تاپ دانشجویی ارزان در تهران',
    'کتونی پیاده‌روی ضد آب در پالادیوم',
  ];

  return (
    <div className="flex-1 flex flex-col h-full bg-[#0c0c10] overflow-hidden relative font-sans">
      {/* Scrollable Message List */}
      <div className="flex-1 overflow-y-auto px-4 py-6 space-y-6">
        {isInitialScreen ? (
          /* Initial Hero matching Torobchat video screenshot */
          <div className="h-full flex flex-col items-center justify-center text-center max-w-xl mx-auto py-12 px-2 animate-fade-in">
            {/* Animated Torob Radish Mascot Logo */}
            <div className="mb-4 cursor-pointer hover:scale-105 transition-transform">
              <TorobLogo size={78} animated={true} withGlow={true} />
            </div>

            <h1 className="text-xl md:text-2xl font-black text-white mb-6 tracking-tight">
              سلام! با چی شروع کنیم؟
            </h1>

            {/* Prompt pills from video */}
            <div className="flex flex-wrap items-center justify-center gap-2.5 max-w-lg">
              {samplePills.map((pill, idx) => (
                <button
                  key={idx}
                  onClick={() => onSendMessage(pill)}
                  className="px-4 py-2 rounded-xl bg-[#141419] hover:bg-[#1e1e26] border border-[#23232c] hover:border-[#e9325a]/60 text-xs text-neutral-300 hover:text-white transition-all hover:scale-[1.02] active:scale-[0.98]"
                >
                  {pill}
                </button>
              ))}
            </div>
          </div>
        ) : (
          /* Conversation Flow */
          <div className="max-w-3xl mx-auto space-y-6">
            {messages.map((msg) => {
              const isUser = msg.sender === 'user';

              return (
                <div
                  key={msg.id}
                  /* In RTL: items-start = RIGHT edge (User, like Telegram), items-end = LEFT edge (Assistant) */
                  className={`flex flex-col ${isUser ? 'items-start' : 'items-end'} space-y-2`}
                >
                  {/* Message Bubble */}
                  <div
                    className={`max-w-[92%] md:max-w-[88%] p-4 text-xs md:text-sm leading-relaxed transition-all ${
                      isUser
                        ? 'bg-[#1b1b24] text-white border border-[#2c2c3b] rounded-2xl rounded-tr-xs'
                        : 'torob-gradient-border bg-[#131318] text-neutral-100 rounded-2xl rounded-tl-xs'
                    }`}
                  >
                    {!isUser && (
                      <div className="flex items-center gap-2 mb-2.5 text-[11px] font-bold text-[#ff4d79]">
                        <TorobLogo size={18} animated={false} withGlow={false} />
                        <span>ترب‌چیت خرید حضوری</span>
                      </div>
                    )}

                    {/* Markdown Renderer for clean bold, lists, and headings */}
                    <MarkdownRenderer content={msg.text} />

                    {/* Dedicated Feature Clarification Questions - Discrete input per question */}
                    {msg.featureClarification && (
                      <FeatureClarificationCard
                        payload={msg.featureClarification}
                        messageId={msg.id}
                        onSubmit={(answers) =>
                          onSubmitFeatureClarification?.(msg.id, answers)
                        }
                      />
                    )}

                    {/* Integrated Comparison Table with Battle Icon */}
                    {msg.comparisonTable && (
                      <div className="mt-4 overflow-x-auto rounded-xl border border-[#24242d] bg-[#0d0d12]">
                        <div className="flex items-center gap-2 text-[11px] font-bold text-[#ff6688] p-2.5 border-b border-[#1c1c24] bg-[#14141a]">
                          <Swords className="w-4 h-4 text-[#ff4d79]" />
                          <span>نبرد و مقایسه سریع گزینه‌های برتر بازار:</span>
                        </div>
                        <table className="w-full text-right text-xs">
                          <thead>
                            <tr className="border-b border-[#1c1c24] bg-[#121217] text-neutral-300">
                              {msg.comparisonTable.headers.map((h, i) => (
                                <th key={i} className="p-2.5 font-bold">
                                  {h}
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-[#1c1c24] text-neutral-300">
                            {msg.comparisonTable.rows.map((row, rIdx) => (
                              <tr key={rIdx} className="hover:bg-white/[0.02]">
                                <td className="p-2.5 font-semibold text-neutral-400">{row.feature}</td>
                                {row.values.map((v, cIdx) => (
                                  <td key={cIdx} className="p-2.5">
                                    {v}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    )}

                    {/* Recommended Product Cards inside chat */}
                    {msg.recommendedProducts && msg.recommendedProducts.length > 0 && (
                      <div className="mt-4 space-y-3">
                        <div className="flex items-center justify-between text-xs font-extrabold text-neutral-200 border-b border-[#2d2d3e] pb-2">
                          <span className="flex items-center gap-1.5 text-white">
                            <span className="w-2 h-2 rounded-full bg-[#ff4d79] animate-pulse" />
                            مدل‌های برگزیده (برای مشاهده مغازه‌ها و قیمت‌ها کلیک کنید):
                          </span>
                          <span className="text-[10px] text-[#ff7597] font-semibold bg-[#ff4d79]/15 px-2 py-0.5 rounded-md border border-[#ff4d79]/30">
                            کارت‌های قابل انتخاب
                          </span>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                          {msg.recommendedProducts.map((prod) => (
                            <div
                              key={prod.id}
                              className="relative p-3.5 rounded-2xl bg-gradient-to-b from-[#202030] via-[#181826] to-[#12121d] border-2 border-[#36364e] hover:border-[#ff4d79] shadow-lg shadow-black/50 hover:shadow-[#e9325a]/25 hover:-translate-y-1 transition-all duration-200 flex flex-col justify-between group cursor-pointer"
                              onClick={() => {
                                onSelectProduct(prod);
                                onNavigateToStores();
                              }}
                            >
                              <div>
                                {/* Product Image Section */}
                                <div className="relative w-full h-36 rounded-xl overflow-hidden bg-[#0d0d15] border border-white/5 mb-3 group/img">
                                  {prod.image ? (
                                    <img
                                      src={prod.image}
                                      alt={prod.title}
                                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                                      loading="lazy"
                                    />
                                  ) : (
                                    <div className="w-full h-full flex items-center justify-center text-neutral-600 bg-[#13131c]">
                                      <span className="text-xs">تصویر محصول</span>
                                    </div>
                                  )}
                                  <div className="absolute inset-0 bg-gradient-to-t from-[#12121d] via-transparent to-transparent opacity-80" />

                                  {/* Badge on Image */}
                                  <div className="absolute top-2 right-2 flex items-center gap-1.5 z-10">
                                    {prod.badge ? (
                                      <span className="text-[10px] text-white bg-[#e9325a] px-2 py-0.5 rounded-md font-bold shadow-md tracking-wide">
                                        {prod.badge}
                                      </span>
                                    ) : (
                                      <span className="text-[10px] text-neutral-300 bg-[#1a1a26]/90 backdrop-blur-sm px-2 py-0.5 rounded-md font-bold border border-white/10">
                                        {prod.category}
                                      </span>
                                    )}
                                  </div>

                                  {/* Action CTA on Image */}
                                  <div className="absolute bottom-2 left-2 z-10">
                                    <span className="text-[10px] font-bold text-white bg-black/60 backdrop-blur-sm border border-white/15 px-2 py-0.5 rounded-full flex items-center gap-1 group-hover:bg-[#e9325a] transition-colors">
                                      <span>انتخاب مدل</span>
                                      <ChevronLeft className="w-3 h-3 group-hover:translate-x-[-2px] transition-transform" />
                                    </span>
                                  </div>
                                </div>

                                {/* Title & Desc */}
                                <h4 className="font-extrabold text-sm text-white group-hover:text-[#ff4d79] transition-colors leading-snug">
                                  {prod.title}
                                </h4>
                                <p className="text-xs text-neutral-300 mt-1.5 leading-relaxed line-clamp-2">
                                  {prod.bestFor}
                                </p>
                              </div>

                              {/* Bottom Pricing (Persian font) & CTA */}
                              <div className="mt-3.5 pt-3 border-t border-[#2a2a3e] flex items-center justify-between gap-2">
                                <div>
                                  <span className="text-[10px] text-neutral-400 block font-medium">کف قیمت در تهران:</span>
                                  <div className="flex items-baseline gap-1 mt-0.5">
                                    <span className="text-sm font-extrabold text-white group-hover:text-[#ff8fa9] transition-colors tracking-tight">
                                      {prod.minPrice.toLocaleString('fa-IR')}
                                    </span>
                                    <span className="text-[11px] text-neutral-400 font-normal">تومان</span>
                                  </div>
                                </div>

                                <div className="px-3 py-1.5 rounded-xl bg-[#e9325a] group-hover:bg-[#ff2d5f] text-white text-xs font-bold flex items-center gap-1.5 shadow-md shadow-[#e9325a]/30 group-hover:scale-105 active:scale-95 transition-all">
                                  <span>{prod.storeCount.toLocaleString('fa-IR')} فروشگاه</span>
                                  <ChevronLeft className="w-3.5 h-3.5 group-hover:translate-x-[-3px] transition-transform" />
                                </div>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}

                    {/* In-Store Shop Offer Cards - Hidden by default to reduce clutter, expandable via toggle phrase */}
                    {msg.shopOffers && msg.shopOffers.length > 0 && (
                      <div className="mt-4 border-t border-[#28283a] pt-3">
                        {/* Toggle Button with clear phrase */}
                        <button
                          type="button"
                          onClick={() => toggleShopOffers(msg.id)}
                          className="w-full flex items-center justify-between p-3 rounded-xl bg-[#161622] hover:bg-[#1e1e2d] border border-[#2c2c3e] hover:border-[#ff4d79]/50 transition-all text-neutral-200 hover:text-white group cursor-pointer"
                        >
                          <div className="flex items-center gap-2.5">
                            <div className="p-1.5 rounded-lg bg-[#e9325a]/15 text-[#ff4d79] group-hover:bg-[#e9325a] group-hover:text-white transition-colors">
                              <Store className="w-4 h-4" />
                            </div>
                            <div className="text-right">
                              <span className="text-xs font-bold block text-white">
                                {expandedShopOffers[msg.id]
                                  ? 'پنهان کردن فروشگاه‌های حضوری این پیشنهاد'
                                  : 'مشاهده فروشگاه‌های حضوری و قیمت‌ها'}
                              </span>
                              <span className="text-[10px] text-neutral-400">
                                {expandedShopOffers[msg.id]
                                  ? 'برای خلوت‌تر شدن صفحه کلیک کنید'
                                  : `${msg.shopOffers.length.toLocaleString('fa-IR')} فروشگاه حضوری دارای موجودی در مراکز خرید و سطح تهران`}
                              </span>
                            </div>
                          </div>

                          <div className="flex items-center gap-1.5 text-xs font-bold text-[#ff7597] bg-[#291b24] px-2.5 py-1 rounded-lg border border-[#e9325a]/30 group-hover:bg-[#e9325a] group-hover:text-white transition-colors">
                            <span>{expandedShopOffers[msg.id] ? 'بستن' : 'نمایش فروشگاه‌ها'}</span>
                            <ChevronDown
                              className={`w-3.5 h-3.5 transition-transform duration-300 ${
                                expandedShopOffers[msg.id] ? 'rotate-180' : ''
                              }`}
                            />
                          </div>
                        </button>

                        {/* Collapsible Store Cards Area */}
                        {expandedShopOffers[msg.id] && (
                          <div className="mt-3 space-y-3 animate-in fade-in slide-in-from-top-2 duration-200">
                            {/* Inline Interactive Map right inside Chat before clicking any external map */}
                            <InteractiveMap
                              offers={msg.shopOffers}
                              userLocation={userLocation}
                              onStartShoppingTrip={onStartShoppingTrip}
                              onChangeLocation={onOpenLocationPicker}
                              compact={true}
                            />

                            <div className="flex items-center justify-between text-[11px] font-bold text-neutral-300 px-1">
                              <span>فروشگاه‌های حضوری نزدیک شما:</span>
                              <button
                                onClick={onNavigateToStores}
                                className="text-[#ff4d79] hover:underline flex items-center gap-1 text-[11px] font-semibold"
                              >
                                <span>مشاهده همه روی نقشه و لیست</span>
                                <ExternalLink className="w-3 h-3" />
                              </button>
                            </div>

                            <div className="space-y-3">
                              {msg.shopOffers.slice(0, 3).map((offer) => (
                                <div
                                  key={offer.id}
                                  className="p-4 rounded-2xl bg-gradient-to-b from-[#20202e] to-[#151522] border-2 border-[#36364e] hover:border-[#ff4d79]/70 shadow-md flex flex-col gap-3 group transition-all"
                                >
                                  {/* Store title & real shop badge */}
                                  <div className="flex items-center justify-between gap-2">
                                    <div className="flex items-center gap-2">
                                      <Store className="w-4 h-4 text-[#e9325a]" />
                                      <span className="font-extrabold text-xs text-white">
                                        {offer.shopName}
                                      </span>
                                    </div>
                                    {offer.isRealShop && (
                                      <span className="text-[9px] px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 font-bold">
                                        فروشگاه رسمی
                                      </span>
                                    )}
                                  </div>

                                  {/* Structured Metadata LABELS */}
                                  <div className="flex flex-wrap items-center gap-1.5 text-[11px]">
                                    {/* Location + Indoor Floor/Unit Label */}
                                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-[#252533] border border-[#37374b] text-neutral-200">
                                      <Building className="w-3 h-3 text-[#ff6688]" />
                                      <span>
                                        {[
                                          offer.mallName || offer.neighborhood,
                                          offer.mallFloor,
                                          offer.mallUnit,
                                        ]
                                          .filter(Boolean)
                                          .join(' • ')}
                                      </span>
                                    </span>

                                    {/* Distance Label */}
                                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-amber-500/15 border border-amber-500/30 text-amber-300 font-bold">
                                      <MapPin className="w-3 h-3 text-amber-400" />
                                      <span>{offer.distanceKm.toLocaleString('fa-IR')} کیلومتر</span>
                                    </span>

                                    {/* Price Freshness Label */}
                                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-[#252533] border border-[#37374b] text-neutral-300">
                                      <Clock className="w-3 h-3 text-neutral-400" />
                                      <span>به‌روزرسانی: {offer.lastUpdated}</span>
                                    </span>

                                    {/* TorobPay Label */}
                                    {offer.torobPayAccepted && (
                                      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-[#e9325a]/15 border border-[#e9325a]/30 text-[#ff4d79] font-bold">
                                        <CheckCircle2 className="w-3 h-3" />
                                        <span>ترب‌پی حضوری</span>
                                      </span>
                                    )}
                                  </div>

                                  {/* Price and Action Buttons */}
                                  <div className="pt-2 border-t border-[#292939] flex items-center justify-between gap-2 flex-wrap">
                                    <div>
                                      <span className="text-[10px] text-neutral-400 block font-medium">قیمت حضوری:</span>
                                      <div className="flex items-baseline gap-1 mt-0.5">
                                        <span className="text-sm font-extrabold text-white">
                                          {offer.price.toLocaleString('fa-IR')}
                                        </span>
                                        <span className="text-[10px] text-neutral-400">تومان</span>
                                      </div>
                                    </div>

                                    <div className="flex items-center gap-1.5">
                                      {onStartShoppingTrip && (
                                        <button
                                          onClick={() => onStartShoppingTrip(offer)}
                                          className="px-3 py-1.5 rounded-xl bg-gradient-to-r from-[#e9325a] to-[#ff4d79] hover:opacity-90 text-white text-xs font-bold flex items-center gap-1 shadow-md shadow-[#e9325a]/25 hover:scale-105 active:scale-95 transition-all cursor-pointer"
                                          title="شروع همراهی هوشمند خرید حضوری"
                                        >
                                          <span>همراهی خرید</span>
                                        </button>
                                      )}

                                      <button
                                        onClick={() => onStartVoiceCall(offer)}
                                        className="px-2.5 py-1.5 rounded-xl bg-[#20202e] hover:bg-[#2c2c3e] text-neutral-200 text-xs font-bold flex items-center gap-1 border border-[#353548] hover:scale-105 active:scale-95 transition-all cursor-pointer"
                                        title="اطلاعات و تماس با فروشگاه"
                                      >
                                        <PhoneCall className="w-3 h-3 text-[#ff80a0]" />
                                        <span>تماس با فروشگاه</span>
                                      </button>
                                    </div>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Integrated Persian Message Timestamp with Vazirmatn font */}
                    <div
                      className={`flex items-center gap-1.5 mt-2.5 pt-1 text-[11px] select-none ${
                        isUser
                          ? 'justify-start text-neutral-400'
                          : 'justify-end text-neutral-500'
                      }`}
                    >
                      <span
                        className="font-medium tracking-tight"
                        style={{ fontFamily: "'Vazirmatn', sans-serif" }}
                      >
                        {msg.timestamp}
                      </span>
                    </div>

                    {/* Subtle, unobtrusive algorithm feedback (Like / Dislike) - Hidden on questions card */}
                    {!isUser && !msg.featureClarification && (
                      <div className="mt-1.5 pt-1.5 border-t border-white/[0.04] flex items-center justify-between text-[10px] text-neutral-400 select-none">
                        <span className="text-neutral-500">
                          {feedbackMap[msg.id]
                            ? '✓ نظر شما در بهبود کیفیت پیشنهادها لحاظ شد'
                            : 'آیا این پیشنهادها مفید بود؟'}
                        </span>
                        {!feedbackMap[msg.id] ? (
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() => {
                                setFeedbackMap((prev) => ({ ...prev, [msg.id]: 'like' }));
                                onFeedback?.(msg.id, 'thumbs_up');
                              }}
                              className="p-1 rounded-md hover:bg-white/10 hover:text-emerald-400 text-neutral-400 transition-colors cursor-pointer"
                              title="مفید بود"
                            >
                              <ThumbsUp className="w-3 h-3" />
                            </button>
                            <button
                              onClick={() => {
                                setFeedbackMap((prev) => ({ ...prev, [msg.id]: 'dislike' }));
                                onFeedback?.(msg.id, 'thumbs_down');
                              }}
                              className="p-1 rounded-md hover:bg-white/10 hover:text-[#ff4d79] text-neutral-400 transition-colors cursor-pointer"
                              title="مناسب نبود (اصلاح اولویت‌ها)"
                            >
                              <ThumbsDown className="w-3 h-3" />
                            </button>
                          </div>
                        ) : (
                          <span className="text-[10px] text-emerald-400/90 font-medium">
                            {feedbackMap[msg.id] === 'like' ? '👍 پسندیده شد' : '👎 ثبت شد'}
                          </span>
                        )}
                      </div>
                    )}
                  </div>

                  {/* Follow-up suggestion chips */}
                  {msg.followUpChips && msg.followUpChips.length > 0 && (
                    <div className="flex flex-wrap gap-1.5 pt-1">
                      {msg.followUpChips.map((chip, cIdx) => (
                        <button
                          key={cIdx}
                          onClick={() => onSendMessage(chip)}
                          className="px-3 py-1 rounded-xl bg-[#14141a] hover:bg-[#1d1d26] border border-[#23232c] hover:border-[#e9325a]/40 text-[11px] text-neutral-300 hover:text-white transition-colors"
                        >
                          {chip}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}

            {/* Thinking / Searching Indicator in Assistant Position (Left in RTL) with Animated Catalog Papers */}
            {isLoading && (
              <div className="flex flex-col items-end animate-fade-in">
                <div className="torob-frame-glow px-4 py-3 rounded-2xl bg-[#131319] text-xs text-neutral-200 flex items-center gap-3">
                  <SearchingPapersAnimation size={34} />
                  <span className="font-bold text-white text-xs">
                    غمت نباشه، دارم می‌گردم برات...
                  </span>
                </div>
              </div>
            )}

            <div ref={messagesEndRef} />
          </div>
        )}
      </div>

      {/* Bottom Input Area - completely removed while answering clarification questions */}
      {!isQuestionFormActive && (
        <div className="p-3.5 md:p-4 bg-[#0c0c10] border-t border-[#181820] animate-in fade-in duration-200">
          <div className="max-w-3xl mx-auto flex flex-col items-center">
            {/* Centered Input Box */}
            <div className="relative w-full rounded-[1.25rem] bg-[#121218] border border-[#20202a] transition-all">
              {/* The traveling electric spark ONLY runs on the initial screen */}
              {isInitialScreen && (
                <svg
                  className="absolute inset-0 w-full h-full pointer-events-none rounded-[1.25rem] overflow-visible"
                  xmlns="http://www.w3.org/2000/svg"
                >
                  <defs>
                    <linearGradient id="singleSparkGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                      <stop offset="0%" stopColor="#e9325a" stopOpacity="0" />
                      <stop offset="35%" stopColor="#e9325a" stopOpacity="0.8" />
                      <stop offset="75%" stopColor="#ff7597" stopOpacity="1" />
                      <stop offset="100%" stopColor="#ffffff" stopOpacity="1" />
                    </linearGradient>
                  </defs>

                  {/* Only ONE spark traveling continuously along the perimeter with graceful midpoint pause */}
                  <rect
                    x="1"
                    y="1"
                    width="calc(100% - 2px)"
                    height="calc(100% - 2px)"
                    rx="18"
                    fill="none"
                    stroke="url(#singleSparkGradient)"
                    strokeWidth="2.4"
                    pathLength="100"
                    className="single-electric-stroke"
                  />
                </svg>
              )}

              {/* Inner Input Content */}
              <form
                onSubmit={handleSend}
                className="relative z-10 flex items-center gap-2 p-1.5"
              >
                <input
                  type="text"
                  value={inputText}
                  onChange={(e) => setInputText(e.target.value)}
                  disabled={isLoading}
                  placeholder="چه چیزی لازم داری؟ (مثلاً اسکوتر شیائومی، گوشی، کتونی...)"
                  className="flex-1 bg-transparent px-3.5 py-2 text-xs md:text-sm text-white placeholder-neutral-500 focus:outline-none"
                />

                <button
                  type="submit"
                  disabled={!inputText.trim() || isLoading}
                  className={`p-2.5 rounded-xl transition-all ${
                    inputText.trim() && !isLoading
                      ? 'bg-[#e9325a] hover:bg-[#d8244c] text-white hover:scale-105 active:scale-95'
                      : 'bg-[#1b1b22] text-neutral-600 cursor-not-allowed'
                  }`}
                  title="ارسال پیام"
                >
                  <SendHorizontal className="w-4 h-4" />
                </button>
              </form>
            </div>

            {/* Torobchat Video Disclaimer note */}
            <p className="text-[10px] text-neutral-500 text-center mt-2">
              ترب‌چیت ممکنه اشتباه کنه؛ اطلاعات مهم مانند قیمت و موجودی قطعی را قبل از مراجعه حضوری استعلام بگیرید.
            </p>
          </div>
        </div>
      )}
    </div>
  );
};

