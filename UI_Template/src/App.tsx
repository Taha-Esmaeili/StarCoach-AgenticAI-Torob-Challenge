import React, { useState } from 'react';
import {
  ActiveTab,
  ChatMessage,
  Product,
  ShopOffer,
  UserLocation,
} from './types';
import {
  PRODUCTS,
  SHOP_OFFERS,
  USER_LOCATIONS,
} from './data/mockData';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { ChatView } from './components/ChatView';
import { StoresView } from './components/StoresView';
import { ComparisonView } from './components/ComparisonView';
import { StoreContactModal } from './components/StoreContactModal';
import { ShoppingCompanionModal } from './components/ShoppingCompanionModal';
import { analyzeUserQueryForFeatures } from './utils/featureClarificationHelper';
import { Clock, X } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('chat');
  const [userLocation, setUserLocation] = useState<UserLocation>(USER_LOCATIONS[1]); // Jomhouri / Charsoo
  const [selectedProduct, setSelectedProduct] = useState<Product>(PRODUCTS[0]);

  // Filters
  const [filterOpenOnly, setFilterOpenOnly] = useState<boolean>(false);
  const [filterTorobPay, setFilterTorobPay] = useState<boolean>(false);
  const [filterInstallment, setFilterInstallment] = useState<boolean>(false);

  // Modals & Sidebar
  const [isSidebarOpen, setIsSidebarOpen] = useState<boolean>(false);
  const [voiceCallOffer, setVoiceCallOffer] = useState<ShopOffer | null>(null);
  const [activeTripOffer, setActiveTripOffer] = useState<ShopOffer | null>(null);
  const [isTripModalOpen, setIsTripModalOpen] = useState<boolean>(false);

  // Chat State
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  // Tabs only appear after recommendations are produced
  const showTabs = messages.some(
    (m) =>
      (m.recommendedProducts && m.recommendedProducts.length > 0) ||
      (m.shopOffers && m.shopOffers.length > 0)
  );

  // Send message handler
  const handleSendMessage = async (text: string) => {
    const userMsg: ChatMessage = {
      id: `msg-${Date.now()}`,
      sender: 'user',
      text,
      timestamp: new Date().toLocaleTimeString('fa-IR', { hour: '2-digit', minute: '2-digit' }),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);

    // Check if this query lacks essential features and we don't have recommendations yet
    const alreadyHasRecommendations = messages.some(
      (m) => (m.recommendedProducts && m.recommendedProducts.length > 0) || m.shopOffers?.length
    );

    const featureClarification = !alreadyHasRecommendations
      ? analyzeUserQueryForFeatures(text)
      : null;

    if (featureClarification) {
      setTimeout(() => {
        const clarificationMsg: ChatMessage = {
          id: `msg-${Date.now() + 1}`,
          sender: 'assistant',
          text: 'برای اینکه دقیق‌تر بتونم راهنماییت کنم، تا حد امکان به سوال‌ها پاسخ بده:',
          timestamp: new Date().toLocaleTimeString('fa-IR', { hour: '2-digit', minute: '2-digit' }),
          featureClarification,
        };
        setMessages((prev) => [...prev, clarificationMsg]);
        setIsLoading(false);
      }, 500);
      return;
    }

    try {
      // Call server endpoint
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: text,
          userLocation,
          selectedProduct,
        }),
      });

      const data = await response.json();
      const replyText = data.reply || 'اطلاعات درخواستی با موفقیت دریافت شد.';

      // Determine product contextual attachments
      const lower = text.toLowerCase();
      let recommendedProducts: Product[] | undefined;
      let comparisonTable: ChatMessage['comparisonTable'] | undefined;
      let shopOffers: ShopOffer[] | undefined;
      let followUpChips: string[] = [];

      if (lower.includes('اسکوتر') || lower.includes('scooter')) {
        recommendedProducts = PRODUCTS.filter((p) => p.category === 'اسکوتر برقی');
        shopOffers = SHOP_OFFERS.filter((o) => o.productId === 'p-scooter-1');
        comparisonTable = {
          headers: ['مشخصه', 'شیائومی 4 Pro', 'ناین‌بات F2 Pro', 'شیائومی Pro 2'],
          rows: [
            { feature: 'کف قیمت', values: ['۴۱.۵ م ت', '۳۶.۵ م ت', '۲۹.۴ م ت'] },
            { feature: 'برد شارژ', values: ['۵۵ کیلومتر', '۴۵ کیلومتر', '۴۵ کیلومتر'] },
            { feature: 'موتور', values: ['۷۰۰ وات', '۹۰۰ وات', '۶۰۰ وات'] },
            { feature: 'ترمز', values: ['دیسکی دوبل + ABS', 'الکتریکی + دیسکی', 'دیسکی'] },
            { feature: 'مناسب برای', values: ['شهری پرچمدار', 'مسیرهای شیب‌دار', 'شروع اقتصادی'] },
          ],
        };
        followUpChips = [
          'فروشگاه‌های باز در چارسو رو نشون بده',
          'استعلام تلفنی موجودی بگیر',
          'اسکوتر بدون صندلی و سبک می‌خوام',
          'بررسی شرایط خرید اقساطی ترب‌پی',
        ];
      } else if (lower.includes('گوشی') || lower.includes('آیفون') || lower.includes('موبایل')) {
        recommendedProducts = PRODUCTS.filter((p) => p.category === 'گوشی موبایل');
        shopOffers = SHOP_OFFERS.filter((o) => o.productId === 'p-phone-1');
        followUpChips = [
          'استعلام رجیستری و قیمت لحظه‌ای آیفون ۱۵ پرو',
          'فروشگاه‌های مجاز چارسو و علاءالدین',
          'خرید قسطی با اسنپ‌پی',
        ];
      } else if (lower.includes('کتونی') || lower.includes('کفش') || lower.includes('نایک')) {
        recommendedProducts = PRODUCTS.filter((p) => p.category === 'کفش و کتونی');
        shopOffers = SHOP_OFFERS.filter((o) => o.productId === 'p-shoes-1');
        followUpChips = [
          'آدرس فروشگاه نایک در پالادیوم',
          'تست سایز پا در کوروش مال',
          'کفش پیاده‌روی ضدآب',
        ];
      } else {
        followUpChips = [
          'من یک اسکوتر برقی مناسب می‌خوام',
          'گوشی عکاسی با بهترین قیمت حضوری',
          'کتونی پیاده‌روی با تخفیف در پالادیوم',
        ];
      }

      const assistantMsg: ChatMessage = {
        id: `msg-${Date.now() + 1}`,
        sender: 'assistant',
        text: replyText,
        timestamp: new Date().toLocaleTimeString('fa-IR', { hour: '2-digit', minute: '2-digit' }),
        recommendedProducts,
        comparisonTable,
        shopOffers,
        followUpChips,
      };

      setMessages((prev) => [...prev, assistantMsg]);
    } catch (err) {
      console.error('Chat error:', err);
      const fallbackMsg: ChatMessage = {
        id: `msg-${Date.now() + 1}`,
        sender: 'assistant',
        text: `برای خرید حضوری اسکوتر برقی در تهران، مدل پرچمدار **شیائومی 4 Pro** و مدل **ناین‌بات سگوی F2 Pro** بهترین انتخاب‌ها هستند. فروشگاه‌های چارسو و علاءالدین در خیابان جمهوری با میانگین فاصله ۱.۲ کیلومتر از شما موجود دارند.`,
        timestamp: new Date().toLocaleTimeString('fa-IR', { hour: '2-digit', minute: '2-digit' }),
        recommendedProducts: PRODUCTS.filter((p) => p.category === 'اسکوتر برقی'),
        shopOffers: SHOP_OFFERS.filter((o) => o.productId === 'p-scooter-1'),
        followUpChips: ['استعلام تلفنی موجودی بگیر', 'فروشگاه‌های باز در چارسو رو نشون بده'],
      };
      setMessages((prev) => [...prev, fallbackMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  // Submit handler for feature clarification questions
  const handleFeatureClarificationSubmit = (
    messageId: string,
    answers: Record<string, string>
  ) => {
    // 1. Mark question payload as submitted
    setMessages((prev) =>
      prev.map((msg) =>
        msg.id === messageId && msg.featureClarification
          ? {
              ...msg,
              featureClarification: {
                ...msg.featureClarification,
                isSubmitted: true,
                submittedAnswers: answers,
              },
            }
          : msg
      )
    );

    // 2. Trigger loading animation
    setIsLoading(true);

    setTimeout(() => {
      const targetMsg = messages.find((m) => m.id === messageId);
      const category = targetMsg?.featureClarification?.category || 'اسکوتر برقی';

      let recommendedProducts: Product[] = [];
      let comparisonTable: ChatMessage['comparisonTable'];
      let shopOffers: ShopOffer[] = [];
      let followUpChips: string[] = [];

      const timingAnswer = answers.timing || 'همین امروز عصر';
      const proximityAnswer = answers.proximity || 'مرکز تخصصی چارسو و جمهوری';
      const paymentAnswer = answers.payment || 'اقساطی با ترب‌پی';
      const usageAnswer = answers.usage || 'مسیرهای شیب‌دار شهری';

      if (category === 'اسکوتر برقی') {
        const isBudgetOrLight = usageAnswer.includes('سبک') || usageAnswer.includes('اقتصادی');
        const isSteepOrLongRange = usageAnswer.includes('شیب') || usageAnswer.includes('برد بالا');

        if (isBudgetOrLight) {
          setSelectedProduct(PRODUCTS[2]); // Mi Pro 2
          recommendedProducts = [PRODUCTS[2], PRODUCTS[0], PRODUCTS[1]];
        } else {
          setSelectedProduct(PRODUCTS[0]); // Xiaomi 4 Pro
          recommendedProducts = [PRODUCTS[0], PRODUCTS[1], PRODUCTS[2]];
        }

        // Base offers
        let offers = [...SHOP_OFFERS.filter((o) => o.productId === 'p-scooter-1')];

        // Apply features
        if (timingAnswer.includes('امروز') || timingAnswer.includes('الان باز')) {
          offers.sort((a, b) => (b.isOpenNow ? 1 : 0) - (a.isOpenNow ? 1 : 0));
        }
        if (paymentAnswer.includes('ترب‌پی') || paymentAnswer.includes('اقساط')) {
          offers.sort((a, b) => (b.torobPayAccepted ? 1 : 0) - (a.torobPayAccepted ? 1 : 0));
        }
        if (proximityAnswer.includes('نزدیک') || proximityAnswer.includes('کیلومتر')) {
          offers.sort((a, b) => a.distanceKm - b.distanceKm);
        }

        shopOffers = offers;

        comparisonTable = {
          headers: ['مشخصه', 'شیائومی 4 Pro', 'ناین‌بات F2 Pro', 'شیائومی Pro 2'],
          rows: [
            { feature: 'کف قیمت حضوری', values: ['۴۱.۵ م ت', '۳۶.۵ م ت', '۲۹.۴ م ت'] },
            { feature: 'برد پیمایش', values: ['۵۵ کیلومتر', '۴۵ کیلومتر', '۴۵ کیلومتر'] },
            { feature: 'توان بیشینه موتور', values: ['۷۰۰ وات', '۹۰۰ وات', '۶۰۰ وات'] },
            { feature: 'سیستم ترمز', values: ['دیسکی دوبل + ABS', 'الکتریکی + دیسکی', 'دیسکی'] },
            {
              feature: 'تطابق با اولویت شما',
              values: [
                isSteepOrLongRange ? 'بهترین برای شیب' : 'پرچمدار شهری',
                'تعلیق نرم جلو',
                isBudgetOrLight ? 'بهترین وزن سبک' : 'اقتصادی',
              ],
            },
          ],
        };

        followUpChips = [
          'فروشگاه‌های باز در چارسو رو نشون بده',
          'استعلام تلفنی موجودی بگیر',
          'بررسی شرایط خرید اقساطی ترب‌پی',
          'شروع همراهی خرید حضوری',
        ];
      } else if (category === 'گوشی موبایل') {
        setSelectedProduct(PRODUCTS[3]);
        recommendedProducts = PRODUCTS.filter((p) => p.category === 'گوشی موبایل');
        shopOffers = SHOP_OFFERS.filter((o) => o.productId === 'p-phone-1');
        followUpChips = [
          'استعلام رجیستری و قیمت لحظه‌ای آیفون ۱۵ پرو',
          'فروشگاه‌های مجاز چارسو و علاءالدین',
          'خرید قسطی با اسنپ‌پی',
        ];
      } else if (category === 'کفش و کتونی') {
        setSelectedProduct(PRODUCTS[6]);
        recommendedProducts = PRODUCTS.filter((p) => p.category === 'کفش و کتونی');
        shopOffers = SHOP_OFFERS.filter((o) => o.productId === 'p-shoes-1');
        followUpChips = [
          'آدرس فروشگاه نایک در پالادیوم',
          'تست سایز پا در کوروش مال',
          'کفش پیاده‌روی ضدآب',
        ];
      } else {
        recommendedProducts = PRODUCTS.slice(0, 3);
        shopOffers = SHOP_OFFERS.slice(0, 3);
      }

      const summaryResponse: ChatMessage = {
        id: `msg-${Date.now() + 1}`,
        sender: 'assistant',
        text: `مشخصات انتخابی شما در الگوریتم ترب اعمال شد:\n\n` +
          `• **زمان مراجعه و خرید:** ${timingAnswer}\n` +
          `• **اولویت مکانی در تهران:** ${proximityAnswer}\n` +
          `• **شیوه پرداخت و تسویه:** ${paymentAnswer}\n` +
          `• **نیاز فنی و بودجه:** ${usageAnswer}\n\n` +
          `بر اساس این پارامترها، مدل‌های متناسب رتبه‌بندی شده و فروشگاه‌های دارای موجودی قطعی در تهران برای شما آماده شدند:`,
        timestamp: new Date().toLocaleTimeString('fa-IR', { hour: '2-digit', minute: '2-digit' }),
        recommendedProducts,
        comparisonTable,
        shopOffers,
        followUpChips,
      };

      setMessages((prev) => [...prev, summaryResponse]);
      setIsLoading(false);
    }, 700);
  };

  const handleResetChat = () => {
    setMessages([]);
    setActiveTab('chat');
  };

  const handleStartVoiceCall = (offer: ShopOffer) => {
    setVoiceCallOffer(offer);
  };

  const handleStartShoppingTrip = (offer: ShopOffer) => {
    setActiveTripOffer(offer);
    setIsTripModalOpen(true);
  };

  return (
    <div className="flex flex-col h-screen w-screen bg-[#0c0c10] text-neutral-100 overflow-hidden font-sans relative">
      {/* Top Header with integrated history button on the left side */}
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        showTabs={showTabs}
        onToggleSidebar={() => setIsSidebarOpen(!isSidebarOpen)}
        isSidebarOpen={isSidebarOpen}
      />

      {/* Main Body with Sidebar + Tabbed Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Responsive Sidebar */}
        <Sidebar
          isOpen={isSidebarOpen}
          onClose={() => setIsSidebarOpen(false)}
          onNewChat={handleResetChat}
          onSelectPrompt={(prompt) => {
            setActiveTab('chat');
            handleSendMessage(prompt);
          }}
          filterOpenOnly={filterOpenOnly}
          setFilterOpenOnly={setFilterOpenOnly}
          filterTorobPay={filterTorobPay}
          setFilterTorobPay={setFilterTorobPay}
          filterInstallment={filterInstallment}
          setFilterInstallment={setFilterInstallment}
        />

        {/* Dynamic View Port */}
        <main className="flex-1 flex flex-col h-full overflow-hidden">
          {activeTab === 'chat' && (
            <ChatView
              messages={messages}
              onSendMessage={handleSendMessage}
              isLoading={isLoading}
              userLocation={userLocation}
              onSelectProduct={(p) => setSelectedProduct(p)}
              onStartVoiceCall={handleStartVoiceCall}
              onStartShoppingTrip={handleStartShoppingTrip}
              onNavigateToStores={() => setActiveTab('stores')}
              onSubmitFeatureClarification={handleFeatureClarificationSubmit}
            />
          )}

          {activeTab === 'stores' && (
            <StoresView
              offers={SHOP_OFFERS.filter((o) => o.productId === selectedProduct.id)}
              userLocation={userLocation}
              setUserLocation={setUserLocation}
              selectedProduct={selectedProduct}
              onStartVoiceCall={handleStartVoiceCall}
              onStartShoppingTrip={handleStartShoppingTrip}
              filterOpenOnly={filterOpenOnly}
              filterTorobPay={filterTorobPay}
              filterInstallment={filterInstallment}
            />
          )}

          {activeTab === 'compare' && (
            <ComparisonView
              selectedProduct={selectedProduct}
              onSelectProduct={(p) => setSelectedProduct(p)}
              onNavigateToStores={() => setActiveTab('stores')}
            />
          )}
        </main>
      </div>

      {/* Store Contact & Direct Phone Call Modal */}
      {voiceCallOffer && (
        <StoreContactModal
          isOpen={!!voiceCallOffer}
          onClose={() => setVoiceCallOffer(null)}
          offer={voiceCallOffer}
        />
      )}

      {/* Live In-Person Shopping Companion Modal */}
      {activeTripOffer && (
        <ShoppingCompanionModal
          isOpen={isTripModalOpen}
          onClose={() => {
            setIsTripModalOpen(false);
            setActiveTripOffer(null);
          }}
          onMinimize={() => setIsTripModalOpen(false)}
          offer={activeTripOffer}
          product={selectedProduct}
          onSwitchOffer={(newOffer) => setActiveTripOffer(newOffer)}
        />
      )}

      {/* Persistent Floating Bottom Bar when trip is minimized */}
      {activeTripOffer && !isTripModalOpen && (
        <div className="fixed bottom-4 left-4 right-4 md:left-auto md:right-6 md:w-96 z-40 bg-[#161622]/95 backdrop-blur-md border border-[#e9325a]/60 p-3 rounded-2xl shadow-2xl flex items-center justify-between gap-3 animate-fade-in">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="relative flex h-3 w-3 shrink-0">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-[#ff4d79] opacity-75"></span>
              <span className="relative inline-flex rounded-full h-3 w-3 bg-[#e9325a]"></span>
            </span>
            <div className="min-w-0 text-xs">
              <div className="font-extrabold text-white truncate">
                همراهی فعال: {activeTripOffer.shopName}
              </div>
              <div className="text-[11px] text-neutral-400 truncate">
                {selectedProduct.title}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={() => setIsTripModalOpen(true)}
              className="px-3 py-1.5 rounded-xl bg-[#e9325a] hover:bg-[#ff2d5f] text-white text-xs font-bold transition-all shadow-md shadow-[#e9325a]/30"
            >
              ادامه همراهی
            </button>
            <button
              onClick={() => setActiveTripOffer(null)}
              className="p-1.5 rounded-lg text-neutral-400 hover:text-white hover:bg-[#20202e] transition-colors"
              title="پایان خرید"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
