import { useState, useRef } from 'react';
import {
  ChatMessage,
  Product,
  ShopOffer,
  UserLocation,
} from './types';
import {
  USER_LOCATIONS,
} from './data/mockData';
import {
  ActiveWeightSlotDto,
  ChatTurnResponseDto,
  DEFAULT_USER_ID,
  mapDtoToClarification,
  mapDtoToProduct,
  mapDtoToShopOffer,
  postChatTurn,
  postFeedback,
} from './api/client';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { ChatView } from './components/ChatView';
import { StoresView } from './components/StoresView';
import { ComparisonView } from './components/ComparisonView';
import { StoreContactModal } from './components/StoreContactModal';
import { ShoppingCompanionModal } from './components/ShoppingCompanionModal';
import { Navigation, ChevronLeft, X } from 'lucide-react';

export function App() {
  const [activeTab, setActiveTab] = useState<'chat' | 'stores' | 'compare'>('chat');
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(true);
  const [userLocation] = useState<UserLocation>(USER_LOCATIONS[0]);
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(null);
  const [liveProducts, setLiveProducts] = useState<Product[]>([]);
  const [allShopOffers, setAllShopOffers] = useState<ShopOffer[]>([]);
  const [activeWeights, setActiveWeights] = useState<ActiveWeightSlotDto[]>([]);

  // Session & User IDs for PostgreSQL + Redis state persistence
  const sessionIdRef = useRef<string>(`sess_${Date.now()}`);
  const userIdRef = useRef<string>(DEFAULT_USER_ID);

  // Store Contact Modal State
  const [contactModalOffer, setContactModalOffer] = useState<ShopOffer | null>(null);

  // Step-by-Step Shopping Companion Modal State (with Minimize to Bar capability)
  const [activeTripOffer, setActiveTripOffer] = useState<ShopOffer | null>(null);
  const [isTripMinimized, setIsTripMinimized] = useState<boolean>(false);

  // In-Store Filters
  const [filterOpenOnly, setFilterOpenOnly] = useState<boolean>(false);
  const [filterTorobPay, setFilterTorobPay] = useState<boolean>(false);
  const [filterInstallment, setFilterInstallment] = useState<boolean>(false);

  // Chat State
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const getPersianTimestamp = () => {
    const now = new Date();
    const dateStr = now.toLocaleDateString('fa-IR', {
      month: 'short',
      day: 'numeric',
    });
    const timeStr = now.toLocaleTimeString('fa-IR', {
      hour: '2-digit',
      minute: '2-digit',
    });
    return `${dateStr}، ساعت ${timeStr}`;
  };

  const applyBackendTurnResponse = (data: ChatTurnResponseDto): ChatMessage => {
    const clarificationPayload = mapDtoToClarification(data.clarification_card);
    const isAskingClarification =
      Boolean(clarificationPayload) || data.widget_type === 'clarification';

    const mappedProducts = isAskingClarification
      ? []
      : (data.recommended_products || []).map(mapDtoToProduct);
    const mappedStores = isAskingClarification
      ? []
      : (data.stores || []).map(mapDtoToShopOffer);

    if (mappedProducts.length > 0) {
      setLiveProducts(mappedProducts);
      setSelectedProduct(mappedProducts[0]);
    }
    if (mappedStores.length > 0) {
      setAllShopOffers(mappedStores);
    }
    if (data.recsys_state?.active_weights) {
      setActiveWeights(data.recsys_state.active_weights);
    }

    return {
      id: `ai-${Date.now()}`,
      sender: 'assistant',
      timestamp: getPersianTimestamp(),
      text: data.assistant_text,
      featureClarification: clarificationPayload,
      recommendedProducts:
        !isAskingClarification && mappedProducts.length > 0 ? mappedProducts : undefined,
      shopOffers:
        !isAskingClarification && mappedStores.length > 0 ? mappedStores : undefined,
      comparisonTable: !isAskingClarification
        ? data.comparison_matrix || undefined
        : undefined,
      followUpChips: isAskingClarification
        ? undefined
        : data.follow_up_chips || [
            'نزدیک‌ترین مغازه باز در تهران',
            'خرید قسطی حضوری با ترب‌پی',
            'ارزان‌ترین فروشگاه این مدل',
          ],
    };
  };

  const handleNewChat = () => {
    sessionIdRef.current = `sess_${Date.now()}`;
    setMessages([]);
    setActiveTab('chat');
  };

  const handleSendMessage = async (text: string) => {
    const userMsg: ChatMessage = {
      id: `user-${Date.now()}`,
      sender: 'user',
      text,
      timestamp: getPersianTimestamp(),
    };

    setMessages((prev) => [...prev, userMsg]);
    setIsLoading(true);
    setActiveTab('chat');

    try {
      const data = await postChatTurn({
        session_id: sessionIdRef.current,
        user_id: userIdRef.current,
        message: text,
        user_location: { lat: userLocation.lat, lng: userLocation.lng },
        ui_overrides: {
          require_open_now: filterOpenOnly,
          require_torob_pay: filterTorobPay,
          require_installment: filterInstallment,
        },
      });
      const aiMsg = applyBackendTurnResponse(data);
      setMessages((prev) => [...prev, aiMsg]);
      setIsLoading(false);
    } catch (err) {
      console.error('Chat turn API error:', err);
      const errorMsg: ChatMessage = {
        id: `ai-err-${Date.now()}`,
        sender: 'assistant',
        timestamp: getPersianTimestamp(),
        text: 'متأسفانه در حال حاضر مشکلی در پردازش درخواست شما پیش آمده است. لطفاً دقایقی دیگر دوباره تلاش کنید و در صورت ادامهٔ مشکل، با پشتیبانی ترب در ارتباط باشید.',
      };
      setMessages((prev) => [...prev, errorMsg]);
      setIsLoading(false);
    }
  };

  // Handle submitting clarification card answers via `/api/v1/feedback` (`T020`)
  const handleFeatureClarificationSubmit = async (
    messageId: string,
    answers: Record<string, string>
  ) => {
    setMessages((prev) =>
      prev.map((m) => {
        if (m.id === messageId && m.featureClarification) {
          return {
            ...m,
            featureClarification: {
              ...m.featureClarification,
              submittedAnswers: answers,
              isSubmitted: true,
            },
          };
        }
        return m;
      })
    );

    setIsLoading(true);
    try {
      const data = await postFeedback({
        session_id: sessionIdRef.current,
        user_id: userIdRef.current,
        feedback_type: 'clarification_choice',
        clarification_answers: answers,
        user_location: { lat: userLocation.lat, lng: userLocation.lng },
      });
      const aiMsg = applyBackendTurnResponse(data);
      setMessages((prev) => [...prev, aiMsg]);
    } catch (err) {
      console.error('Feedback API error:', err);
      const errorMsg: ChatMessage = {
        id: `ai-err-${Date.now()}`,
        sender: 'assistant',
        timestamp: getPersianTimestamp(),
        text: 'متأسفانه در ثبت پاسخ شما مشکلی پیش آمده است. لطفاً دوباره تلاش کنید یا در صورت تداوم مشکل با پشتیبانی ترب تماس بگیرید.',
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsLoading(false);
    }
  };

  const recordPositiveOfferSelection = (offer: ShopOffer) => {
    void postFeedback({
      session_id: sessionIdRef.current,
      user_id: userIdRef.current,
      feedback_type: 'thumbs_up',
      target_offer_id: offer.id,
      target_product_id: offer.productId,
      user_location: { lat: userLocation.lat, lng: userLocation.lng },
    })
      .then((data) => {
        if (data.recsys_state?.active_weights) {
          setActiveWeights(data.recsys_state.active_weights);
        }
      })
      .catch(() => {
        // non-blocking revealed-preference telemetry
      });
  };

  // Handle explicit 👍 / 👎 feedback (`thumbs_down` triggers Round-2 Dissatisfaction Clarification)
  const handleFeedback = async (
    messageId: string,
    feedbackType: 'thumbs_up' | 'thumbs_down'
  ) => {
    const targetMsg = messages.find((m) => m.id === messageId);
    const primaryOffer = targetMsg?.shopOffers?.[0] || allShopOffers[0];
    try {
      const data = await postFeedback({
        session_id: sessionIdRef.current,
        user_id: userIdRef.current,
        feedback_type: feedbackType,
        target_offer_id: feedbackType === 'thumbs_up' ? primaryOffer?.id : undefined,
        target_product_id: feedbackType === 'thumbs_up' ? primaryOffer?.productId : undefined,
        user_location: { lat: userLocation.lat, lng: userLocation.lng },
      });
      if (data.recsys_state?.active_weights) {
        setActiveWeights(data.recsys_state.active_weights);
      }
      if (feedbackType === 'thumbs_down' && data.clarification_card) {
        const aiMsg = applyBackendTurnResponse(data);
        setMessages((prev) => [...prev, aiMsg]);
      }
    } catch {
      // ignore if offline
    }
  };

  // Handle interactive 15-parameter weight slider override in Sidebar (`T019`)
  const handleWeightChange = async (key: string, val: number) => {
    setActiveWeights((prev) =>
      prev.map((s) => (s.key === key ? { ...s, unconstrained_weight: val } : s))
    );
    try {
      const data = await postFeedback({
        session_id: sessionIdRef.current,
        user_id: userIdRef.current,
        feedback_type: 'weight_override',
        weight_overrides: { [key]: val },
        user_location: { lat: userLocation.lat, lng: userLocation.lng },
      });
      if (data.recsys_state?.active_weights) {
        setActiveWeights(data.recsys_state.active_weights);
      }
      if (data.stores && data.stores.length > 0) {
        setAllShopOffers(data.stores.map(mapDtoToShopOffer));
      }
    } catch {
      // ignore if offline
    }
  };

  return (
    <div
      dir="rtl"
      className="h-screen w-screen overflow-hidden flex flex-col bg-[#0c0c10] text-white select-none md:select-auto font-sans"
    >
      {/* Top Navbar */}
      <Header
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        showTabs={messages.length > 0}
        onToggleSidebar={() => setSidebarOpen((p) => !p)}
        isSidebarOpen={sidebarOpen}
      />

      {/* Main Content Area with Right Sidebar */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Right Collapsible Sidebar */}
        <Sidebar
          isOpen={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          onNewChat={handleNewChat}
          onSelectPrompt={(prompt) => handleSendMessage(prompt)}
          filterOpenOnly={filterOpenOnly}
          setFilterOpenOnly={setFilterOpenOnly}
          filterTorobPay={filterTorobPay}
          setFilterTorobPay={setFilterTorobPay}
          filterInstallment={filterInstallment}
          setFilterInstallment={setFilterInstallment}
          activeWeights={activeWeights}
          onWeightChange={handleWeightChange}
        />

        {/* Center Main View */}
        <main className="flex-1 flex flex-col h-full overflow-hidden relative">
          {activeTab === 'chat' && (
            <ChatView
              messages={messages}
              onSendMessage={handleSendMessage}
              isLoading={isLoading}
              userLocation={userLocation}
              onSelectProduct={(p) => setSelectedProduct(p)}
              onStartVoiceCall={(offer) => {
                setContactModalOffer(offer);
                recordPositiveOfferSelection(offer);
              }}
              onStartShoppingTrip={(offer) => {
                setActiveTripOffer(offer);
                setIsTripMinimized(false);
                recordPositiveOfferSelection(offer);
              }}
              onNavigateToStores={() => setActiveTab('stores')}
              onSubmitFeatureClarification={handleFeatureClarificationSubmit}
              onFeedback={handleFeedback}
            />
          )}

          {activeTab === 'stores' && (
            <StoresView
              offers={allShopOffers}
              selectedProduct={selectedProduct}
              userLocation={userLocation}
              onStartVoiceCall={(offer) => {
                setContactModalOffer(offer);
                recordPositiveOfferSelection(offer);
              }}
              onStartShoppingTrip={(offer) => {
                setActiveTripOffer(offer);
                setIsTripMinimized(false);
                recordPositiveOfferSelection(offer);
              }}
              filterOpenOnly={filterOpenOnly}
              filterTorobPay={filterTorobPay}
              filterInstallment={filterInstallment}
            />
          )}

          {activeTab === 'compare' && (
            <ComparisonView
              products={liveProducts}
              offers={allShopOffers}
              onSelectProductForStores={(prod) => {
                setSelectedProduct(prod);
                setActiveTab('stores');
              }}
            />
          )}
        </main>
      </div>

      {/* Store Direct Contact Info Modal */}
      {contactModalOffer && (
        <StoreContactModal
          isOpen={!!contactModalOffer}
          onClose={() => setContactModalOffer(null)}
          offer={contactModalOffer}
        />
      )}

      {/* Full Step-by-Step In-Person Shopping Companion Modal */}
      {activeTripOffer &&
        !isTripMinimized &&
        (liveProducts.find((p) => p.id === activeTripOffer.productId) ||
          selectedProduct ||
          liveProducts[0]) && (
          <ShoppingCompanionModal
            isOpen={true}
            onClose={() => {
              setActiveTripOffer(null);
              setIsTripMinimized(false);
            }}
            onMinimize={() => setIsTripMinimized(true)}
            offer={activeTripOffer}
            userLocation={userLocation}
            product={
              (liveProducts.find((p) => p.id === activeTripOffer.productId) ||
                selectedProduct ||
                liveProducts[0])!
            }
            onSwitchOffer={(newOffer) => setActiveTripOffer(newOffer)}
          />
        )}

      {/* Floating Minimized Bar for Active Shopping Trip */}
      {activeTripOffer && isTripMinimized && (
        <div className="fixed bottom-4 left-4 right-4 md:left-8 md:right-auto md:w-96 z-40 p-3 rounded-2xl bg-gradient-to-r from-[#1f1622] via-[#191926] to-[#14141f] border-2 border-[#e9325a] shadow-2xl shadow-black/80 flex items-center justify-between gap-3 animate-fade-in">
          <div
            onClick={() => setIsTripMinimized(false)}
            className="flex items-center gap-2.5 min-w-0 cursor-pointer flex-1"
          >
            <div className="w-8 h-8 rounded-xl bg-[#e9325a] text-white flex items-center justify-center shrink-0">
              <Navigation className="w-4 h-4 animate-pulse" />
            </div>
            <div className="min-w-0">
              <div className="text-[10px] font-bold text-[#ff80a0]">
                همراه خرید حضوری فعال
              </div>
              <div className="text-xs font-extrabold text-white truncate">
                {activeTripOffer.shopName}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            <button
              onClick={() => setIsTripMinimized(false)}
              className="px-2.5 py-1.5 rounded-xl bg-[#e9325a] hover:bg-[#ff2d5f] text-white text-[11px] font-bold flex items-center gap-1 transition-colors cursor-pointer"
            >
              <span>ادامه</span>
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
            <button
              onClick={() => {
                setActiveTripOffer(null);
                setIsTripMinimized(false);
              }}
              className="p-1.5 rounded-xl text-neutral-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
              title="پایان همراهی"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
export default App;
