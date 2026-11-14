import { useState, useRef, useEffect, useCallback } from 'react';
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
  SessionHistoryDetailDto,
  deleteUserSession,
  fetchSessionDetail,
  fetchUserSessions,
  getOrCreatePersistentUserId,
  mapDtoToClarification,
  mapDtoToProduct,
  mapDtoToShopOffer,
  postChatTurn,
  postFeedback,
} from './api/client';
import { Header } from './components/Header';
import { Sidebar, SidebarSessionItem } from './components/Sidebar';
import { ChatView } from './components/ChatView';
import { StoresView } from './components/StoresView';
import { ComparisonView } from './components/ComparisonView';
import { StoreContactModal } from './components/StoreContactModal';
import { ShoppingCompanionModal } from './components/ShoppingCompanionModal';
import { LocationPickerModal } from './components/LocationPickerModal';
import { Navigation, ChevronLeft, X } from 'lucide-react';

const ACTIVE_SESSION_STORAGE_KEY = 'torob_active_session_id';
const THREADS_CACHE_STORAGE_KEY = 'torob_threads_cache_v1';
const USER_LOCATION_STORAGE_KEY = 'torob_user_location_v1';

function loadInitialUserLocation(): UserLocation {
  if (typeof window === 'undefined') return USER_LOCATIONS[0];
  try {
    const raw = window.localStorage.getItem(USER_LOCATION_STORAGE_KEY);
    if (!raw) return USER_LOCATIONS[0];
    const parsed = JSON.parse(raw);
    if (
      parsed &&
      typeof parsed.lat === 'number' &&
      typeof parsed.lng === 'number' &&
      typeof parsed.name === 'string'
    ) {
      return parsed as UserLocation;
    }
  } catch {
    // ignore corrupt localStorage
  }
  return USER_LOCATIONS[0];
}
// shortcut: cap localStorage cache at 15 rich threads to stay well below 5MB browser quota; older threads hydrate on-demand from PostgreSQL.
const MAX_LOCAL_CACHED_THREADS = 15;

interface CachedThreadState {
  sessionId: string;
  title: string;
  updatedAt: string;
  messages: ChatMessage[];
  liveProducts: Product[];
  allShopOffers: ShopOffer[];
  selectedProduct: Product | null;
  activeWeights: ActiveWeightSlotDto[];
  filterOpenOnly: boolean;
  filterTorobPay: boolean;
  filterInstallment: boolean;
}

function formatPersianTimestamp(isoOrDate?: string | Date): string {
  const d = isoOrDate ? new Date(isoOrDate) : new Date();
  const validDate = Number.isNaN(d.getTime()) ? new Date() : d;
  const dateStr = validDate.toLocaleDateString('fa-IR', {
    month: 'short',
    day: 'numeric',
  });
  const timeStr = validDate.toLocaleTimeString('fa-IR', {
    hour: '2-digit',
    minute: '2-digit',
  });
  return `${dateStr}، ساعت ${timeStr}`;
}

function readThreadsCache(): Record<string, CachedThreadState> {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(THREADS_CACHE_STORAGE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function writeThreadsCache(cache: Record<string, CachedThreadState>): void {
  if (typeof window === 'undefined') return;
  const entries = Object.values(cache).sort((a, b) =>
    (b.updatedAt || '').localeCompare(a.updatedAt || '')
  );
  const trySave = (limit: number) => {
    const trimmed: Record<string, CachedThreadState> = {};
    for (const item of entries.slice(0, limit)) {
      trimmed[item.sessionId] = item;
    }
    window.localStorage.setItem(THREADS_CACHE_STORAGE_KEY, JSON.stringify(trimmed));
  };
  try {
    trySave(MAX_LOCAL_CACHED_THREADS);
  } catch {
    try {
      trySave(4);
    } catch {
      // ignore storage quota errors; PostgreSQL remains durable source of truth
    }
  }
}

function buildThreadStateFromServerDetail(
  detail: SessionHistoryDetailDto
): CachedThreadState {
  let latestProducts: Product[] = [];
  let latestOffers: ShopOffer[] = [];
  let latestWeights: ActiveWeightSlotDto[] = detail.active_weights || [];

  const rebuiltMessages: ChatMessage[] = (detail.ui_turns || []).map((entry, idx) => {
    const timestamp = formatPersianTimestamp(entry.created_at);
    if (entry.sender === 'user') {
      return {
        id: entry.id || `user-${idx}`,
        sender: 'user',
        text: entry.text,
        timestamp,
      };
    }

    const tr = entry.turn_response;
    if (!tr) {
      return {
        id: entry.id || `ai-${idx}`,
        sender: 'assistant',
        text: entry.text,
        timestamp,
      };
    }

    let clarificationPayload = mapDtoToClarification(tr.clarification_card);
    if (
      clarificationPayload &&
      (entry.is_submitted ||
        (entry.submitted_answers && Object.keys(entry.submitted_answers).length > 0))
    ) {
      clarificationPayload = {
        ...clarificationPayload,
        submittedAnswers: entry.submitted_answers || {},
        isSubmitted: true,
      };
    }

    const isAskingClarification =
      Boolean(clarificationPayload) || tr.widget_type === 'clarification';
    const mappedProducts = isAskingClarification
      ? []
      : (tr.recommended_products || []).map(mapDtoToProduct);
    const mappedStores = isAskingClarification
      ? []
      : (tr.stores || []).map(mapDtoToShopOffer);

    if (mappedProducts.length > 0) latestProducts = mappedProducts;
    if (mappedStores.length > 0) latestOffers = mappedStores;
    if (tr.recsys_state?.active_weights?.length) {
      latestWeights = tr.recsys_state.active_weights;
    }

    return {
      id: entry.id || `ai-${idx}`,
      sender: 'assistant',
      timestamp,
      text: tr.assistant_text || entry.text,
      featureClarification: clarificationPayload,
      recommendedProducts:
        !isAskingClarification && mappedProducts.length > 0 ? mappedProducts : undefined,
      shopOffers:
        !isAskingClarification && mappedStores.length > 0 ? mappedStores : undefined,
      comparisonTable: !isAskingClarification
        ? tr.comparison_matrix || undefined
        : undefined,
      followUpChips: isAskingClarification
        ? undefined
        : tr.follow_up_chips && tr.follow_up_chips.length > 0
          ? tr.follow_up_chips
          : undefined,
    };
  });

  const matchedSelected =
    (detail.selected_product_id &&
      latestProducts.find((p) => p.id === String(detail.selected_product_id))) ||
    latestProducts[0] ||
    null;

  return {
    sessionId: detail.session_id,
    title: detail.title || 'گفت‌وگوی خرید حضوری',
    updatedAt: detail.updated_at || new Date().toISOString(),
    messages: rebuiltMessages,
    liveProducts: latestProducts,
    allShopOffers: latestOffers,
    selectedProduct: matchedSelected,
    activeWeights: latestWeights,
    filterOpenOnly: Boolean(detail.hard_constraints?.require_open_now),
    filterTorobPay: Boolean(detail.require_torob_pay),
    filterInstallment: Boolean(detail.hard_constraints?.require_installment),
  };
}

function loadInitialSessionBoot() {
  const cache = readThreadsCache();
  const sortedCached = Object.values(cache)
    .filter((t) => t.messages && t.messages.length > 0)
    .sort((a, b) => (b.updatedAt || '').localeCompare(a.updatedAt || ''));

  let savedActiveId: string | null = null;
  if (typeof window !== 'undefined') {
    try {
      savedActiveId = window.localStorage.getItem(ACTIVE_SESSION_STORAGE_KEY);
    } catch {
      savedActiveId = null;
    }
  }

  const initialSessionId =
    savedActiveId || sortedCached[0]?.sessionId || `sess_${Date.now()}`;
  const activeCached = cache[initialSessionId] || null;

  const initialSessionsList: SidebarSessionItem[] = sortedCached.map((t) => ({
    sessionId: t.sessionId,
    title: t.title,
  }));

  return {
    hadSavedActiveId: Boolean(savedActiveId),
    initialSessionId,
    activeCached,
    initialSessionsList,
  };
}

export function App() {
  const bootRef = useRef(loadInitialSessionBoot());
  const boot = bootRef.current;

  const [activeTab, setActiveTab] = useState<'chat' | 'stores' | 'compare'>('chat');
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(false);
  const [userLocation, setUserLocation] = useState<UserLocation>(loadInitialUserLocation);
  const [locationPickerOpen, setLocationPickerOpen] = useState<boolean>(false);
  const [selectedProduct, setSelectedProduct] = useState<Product | null>(
    boot.activeCached?.selectedProduct || null
  );
  const [liveProducts, setLiveProducts] = useState<Product[]>(
    boot.activeCached?.liveProducts || []
  );
  const [allShopOffers, setAllShopOffers] = useState<ShopOffer[]>(
    boot.activeCached?.allShopOffers || []
  );
  const [activeWeights, setActiveWeights] = useState<ActiveWeightSlotDto[]>(
    boot.activeCached?.activeWeights || []
  );

  // Durable User & Session IDs across browser refreshes (PostgreSQL + localStorage)
  const userIdRef = useRef<string>(getOrCreatePersistentUserId());
  const sessionIdRef = useRef<string>(boot.initialSessionId);
  const [activeSessionId, setActiveSessionId] = useState<string>(boot.initialSessionId);
  const [sessionsList, setSessionsList] = useState<SidebarSessionItem[]>(
    boot.initialSessionsList
  );

  // Store Contact Modal State
  const [contactModalOffer, setContactModalOffer] = useState<ShopOffer | null>(null);

  // Step-by-Step Shopping Companion Modal State (with Minimize to Bar capability)
  const [activeTripOffer, setActiveTripOffer] = useState<ShopOffer | null>(null);
  const [isTripMinimized, setIsTripMinimized] = useState<boolean>(false);

  // In-Store Filters
  const [filterOpenOnly, setFilterOpenOnly] = useState<boolean>(
    boot.activeCached?.filterOpenOnly || false
  );
  const [filterTorobPay, setFilterTorobPay] = useState<boolean>(
    boot.activeCached?.filterTorobPay || false
  );
  const [filterInstallment, setFilterInstallment] = useState<boolean>(
    boot.activeCached?.filterInstallment || false
  );

  // Chat State
  const [messages, setMessages] = useState<ChatMessage[]>(
    boot.activeCached?.messages || []
  );
  const [isLoading, setIsLoading] = useState<boolean>(false);

  const getPersianTimestamp = () => formatPersianTimestamp();

  const applyThreadState = useCallback((state: CachedThreadState) => {
    sessionIdRef.current = state.sessionId;
    setActiveSessionId(state.sessionId);
    setMessages(state.messages);
    setLiveProducts(state.liveProducts);
    setAllShopOffers(state.allShopOffers);
    setSelectedProduct(state.selectedProduct);
    setActiveWeights(state.activeWeights);
    setFilterOpenOnly(state.filterOpenOnly);
    setFilterTorobPay(state.filterTorobPay);
    setFilterInstallment(state.filterInstallment);
  }, []);

  const hydrateSessionFromServer = useCallback(
    async (targetSessionId: string, showSpinner: boolean) => {
      if (showSpinner) setIsLoading(true);
      try {
        const detail = await fetchSessionDetail(targetSessionId, userIdRef.current);
        if (sessionIdRef.current !== targetSessionId) return;
        const rebuilt = buildThreadStateFromServerDetail(detail);
        applyThreadState(rebuilt);
        const cache = readThreadsCache();
        cache[rebuilt.sessionId] = rebuilt;
        writeThreadsCache(cache);
      } catch {
        // Keep local cached state if offline or 404
      } finally {
        if (showSpinner) setIsLoading(false);
      }
    },
    [applyThreadState]
  );

  // Sync saved conversation list & missing thread state from PostgreSQL on mount
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetchUserSessions(userIdRef.current);
        if (cancelled) return;
        const serverItems: SidebarSessionItem[] = (res.sessions || []).map((s) => ({
          sessionId: s.session_id,
          title: s.title,
        }));

        setSessionsList((prev) => {
          const seen = new Set(serverItems.map((s) => s.sessionId));
          const merged = [...serverItems];
          for (const localItem of prev) {
            if (!seen.has(localItem.sessionId)) {
              merged.push(localItem);
            }
          }
          return merged;
        });

        const currentSid = sessionIdRef.current;
        const hasLocalMessages = (readThreadsCache()[currentSid]?.messages?.length || 0) > 0;
        if (!hasLocalMessages) {
          if (serverItems.some((s) => s.sessionId === currentSid)) {
            await hydrateSessionFromServer(currentSid, true);
          } else if (!boot.hadSavedActiveId && serverItems.length > 0) {
            const newestSid = serverItems[0].sessionId;
            sessionIdRef.current = newestSid;
            setActiveSessionId(newestSid);
            await hydrateSessionFromServer(newestSid, true);
          }
        }
      } catch {
        // Local cache continues seamlessly if backend session list is unreachable
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [boot.hadSavedActiveId, hydrateSessionFromServer]);

  // Persist active session pointer & non-empty thread snapshot to localStorage
  useEffect(() => {
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.setItem(ACTIVE_SESSION_STORAGE_KEY, activeSessionId);
      } catch {
        // ignore
      }
    }
    if (messages.length === 0) return;

    const firstUserMsg = messages.find((m) => m.sender === 'user');
    const derivedTitle = (firstUserMsg?.text || 'گفت‌وگوی خرید حضوری').slice(0, 52);
    const cache = readThreadsCache();
    const existingTitle = cache[activeSessionId]?.title;
    const title = existingTitle || derivedTitle;

    cache[activeSessionId] = {
      sessionId: activeSessionId,
      title,
      updatedAt: new Date().toISOString(),
      messages,
      liveProducts,
      allShopOffers,
      selectedProduct,
      activeWeights,
      filterOpenOnly,
      filterTorobPay,
      filterInstallment,
    };
    writeThreadsCache(cache);

    setSessionsList((prev) => {
      const rest = prev.filter((item) => item.sessionId !== activeSessionId);
      return [{ sessionId: activeSessionId, title }, ...rest];
    });
  }, [
    activeSessionId,
    messages,
    liveProducts,
    allShopOffers,
    selectedProduct,
    activeWeights,
    filterOpenOnly,
    filterTorobPay,
    filterInstallment,
  ]);

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
    const nextSessionId = `sess_${Date.now()}`;
    sessionIdRef.current = nextSessionId;
    setActiveSessionId(nextSessionId);
    setMessages([]);
    setLiveProducts([]);
    setAllShopOffers([]);
    setSelectedProduct(null);
    setActiveWeights([]);
    setActiveTripOffer(null);
    setIsTripMinimized(false);
    setActiveTab('chat');
  };

  const handleSelectSession = (targetSessionId: string) => {
    if (targetSessionId === activeSessionId && messages.length > 0) {
      setActiveTab('chat');
      return;
    }
    sessionIdRef.current = targetSessionId;
    setActiveSessionId(targetSessionId);
    setActiveTripOffer(null);
    setIsTripMinimized(false);
    setActiveTab('chat');

    const cached = readThreadsCache()[targetSessionId];
    if (cached && cached.messages.length > 0) {
      applyThreadState(cached);
      void hydrateSessionFromServer(targetSessionId, false);
    } else {
      setMessages([]);
      setLiveProducts([]);
      setAllShopOffers([]);
      setSelectedProduct(null);
      setActiveWeights([]);
      void hydrateSessionFromServer(targetSessionId, true);
    }
  };

  const handleDeleteSession = (targetSessionId: string) => {
    const cache = readThreadsCache();
    delete cache[targetSessionId];
    writeThreadsCache(cache);

    const remaining = sessionsList.filter((item) => item.sessionId !== targetSessionId);
    setSessionsList(remaining);

    void deleteUserSession(targetSessionId, userIdRef.current).catch(() => {
      // ignore network failure after local removal
    });

    if (targetSessionId === activeSessionId) {
      if (remaining.length > 0) {
        handleSelectSession(remaining[0].sessionId);
      } else {
        handleNewChat();
      }
    }
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

  // Handle manual map pin location update & immediate store re-ranking (`location_update`)
  const handleConfirmLocation = async (nextLocation: UserLocation) => {
    setUserLocation(nextLocation);
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.setItem(
          USER_LOCATION_STORAGE_KEY,
          JSON.stringify(nextLocation)
        );
      } catch {
        // ignore storage errors
      }
    }

    if (messages.length === 0) return;

    try {
      const data = await postFeedback({
        session_id: sessionIdRef.current,
        user_id: userIdRef.current,
        feedback_type: 'location_update',
        user_location: { lat: nextLocation.lat, lng: nextLocation.lng },
      });
      if (data.recsys_state?.active_weights) {
        setActiveWeights(data.recsys_state.active_weights);
      }
      if (data.stores && data.stores.length > 0) {
        const updatedOffers = data.stores.map(mapDtoToShopOffer);
        setAllShopOffers(updatedOffers);
        setMessages((prev) => {
          let lastOffersIdx = -1;
          for (let i = prev.length - 1; i >= 0; i -= 1) {
            if (prev[i].shopOffers && prev[i].shopOffers!.length > 0) {
              lastOffersIdx = i;
              break;
            }
          }
          if (lastOffersIdx === -1) return prev;
          return prev.map((m, idx) =>
            idx === lastOffersIdx ? { ...m, shopOffers: updatedOffers } : m
          );
        });
        setActiveTripOffer((prevTrip) => {
          if (!prevTrip) return null;
          return updatedOffers.find((o) => o.id === prevTrip.id) || prevTrip;
        });
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
        userLocation={userLocation}
        onOpenLocationPicker={() => setLocationPickerOpen(true)}
      />

      {/* Main Content Area with Right Sidebar */}
      <div className="flex-1 flex overflow-hidden relative">
        {/* Right Collapsible Sidebar */}
        <Sidebar
          isOpen={sidebarOpen}
          onClose={() => setSidebarOpen(false)}
          onNewChat={handleNewChat}
          sessions={sessionsList}
          activeSessionId={activeSessionId}
          onSelectSession={handleSelectSession}
          onDeleteSession={handleDeleteSession}
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
              onOpenLocationPicker={() => setLocationPickerOpen(true)}
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
              onOpenLocationPicker={() => setLocationPickerOpen(true)}
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

      {/* Manual Map Pin Location Picker Modal */}
      <LocationPickerModal
        isOpen={locationPickerOpen}
        initialLocation={userLocation}
        onClose={() => setLocationPickerOpen(false)}
        onConfirmLocation={handleConfirmLocation}
      />

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
