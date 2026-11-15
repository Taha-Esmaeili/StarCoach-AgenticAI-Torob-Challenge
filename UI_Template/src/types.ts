/**
 * Types for Torob In-Store Shopping Assistant (ترب‌چیت حضوری)
 */

export interface Product {
  id: string;
  title: string;
  englishTitle: string;
  category: string;
  brand: string;
  image: string;
  minPrice: number;
  maxPrice: number;
  storeCount: number;
  rating: number;
  pros: string[];
  cons: string[];
  specs: Record<string, string>;
  bestFor: string;
  badge?: string;
}

export interface ShopOffer {
  id: string;
  productId: string;
  shopId: string;
  shopName: string;
  isRealShop: boolean; // From the 112 real shops in dataset
  hasWebsiteOrInstagram?: boolean;
  websiteUrl?: string;
  instagramHandle?: string;
  mallName: string;
  mallFloor: string;
  mallUnit: string;
  mallNote: string; // Precise in-mall guidance (e.g. "جنب آسانسور شیشه‌ای، راهرو جنوبی")
  neighborhood: string;
  address: string;
  coordinates: {
    lat: number;
    lng: number;
  };
  distanceKm: number;
  estimatedDrivingMins: number;
  estimatedWalkingMins: number;
  price: number;
  officialListPrice: number;
  discountToman: number;
  lastUpdated: string; // e.g. "۲ ساعت پیش", "۳ روز پیش"
  lastUpdatedTimestamp: number;
  warranty: string;
  torobPayAccepted: boolean;
  installmentOptions: string[];
  kallabargSupported: boolean;
  workingHours: string;
  isOpenNow: boolean;
  phone: string;
  reputationScore: number; // 0 - 5
  historyInTorobYears: number;
  stockStatus: 'confirmed_in_stock' | 'unconfirmed_in_catalog' | 'out_of_stock';
  mallFloorGuide?: string;
  utilityScore?: number;
  paretoRole?: 'best_overall' | 'closest_open' | 'lowest_price' | 'standard';
  paretoBadge?: string;
  whyThisShop?: string[];
}

export interface UserLocation {
  id: string;
  name: string;
  area: string;
  lat: number;
  lng: number;
}

export interface FeatureQuestion {
  id: string; // e.g. 'timing' | 'proximity' | 'payment' | 'usage'
  title: string; // e.g. 'زمان خرید حضوری'
  question: string; // e.g. 'کی قصد مراجعه به فروشگاه و خرید حضوری دارید؟'
  impactBadge: string; // e.g. 'بررسی باز بودن فروشگاه و موجودی لحظه‌ای'
  iconType: 'time' | 'location' | 'payment' | 'usage';
  options: string[]; // quick selectable chips
  placeholder: string; // custom answer placeholder for dedicated input box
}

export interface FeatureClarificationPayload {
  category: string;
  categoryTitle: string;
  questions: FeatureQuestion[];
  isSubmitted?: boolean;
  submittedAnswers?: Record<string, string>;
}

export interface ChatMessage {
  id: string;
  sender: 'user' | 'assistant' | 'system';
  text: string;
  timestamp: string;
  isThinking?: boolean;
  comparisonTable?: {
    headers: string[];
    rows: { feature: string; values: string[] }[];
  };
  recommendedProducts?: Product[];
  selectedProduct?: Product;
  shopOffers?: ShopOffer[];
  followUpChips?: string[];
  featureClarification?: FeatureClarificationPayload;
}

export type ActiveTab = 'chat' | 'stores' | 'compare';
