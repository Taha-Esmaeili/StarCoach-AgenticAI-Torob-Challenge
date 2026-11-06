/**
 * Typed API client for Torob Smart In-Person Shopping Assistant (/api/v1/*)
 * Maps backend Pydantic schemas (specs/001-torob-shopping-assistant/contracts/api.md)
 * directly to UI_Template/src/types.ts interfaces.
 */

import type {
  FeatureClarificationPayload,
  Product,
  ShopOffer,
} from '../types';

export interface CoordinatesDto {
  lat: number;
  lng: number;
}

export interface UIOverridesDto {
  require_open_now?: boolean;
  require_installment?: boolean;
  require_warranty?: boolean;
  require_torob_pay?: boolean;
  max_distance_km?: number | null;
  max_price_toman?: number | null;
}

export interface ActiveWeightSlotDto {
  slot: number;
  key: string;
  label_fa: string;
  slot_group: 'base' | 'persona' | 'dynamic';
  weight: number;
  unconstrained_weight: number;
  confidence: number;
}

export interface RecSysStateDto {
  effective_confidence: number;
  clarification_count: number;
  dissatisfaction_triggered: boolean;
  active_weights: ActiveWeightSlotDto[];
  hard_constraints: {
    require_open_now: boolean;
    require_installment: boolean;
    require_warranty: boolean;
  };
}

export interface MallMicroGuideDto {
  mall_name?: string | null;
  floor_label?: string | null;
  unit_label?: string | null;
  note_fa?: string | null;
}

export interface ScoredStoreOfferDto {
  offer_id: string | number;
  product_id: string | number;
  product_name: string;
  shop_id: string | number;
  shop_name: string;
  price_toman: number;
  utility_score: number;
  pareto_role: 'best_overall' | 'closest_open' | 'lowest_price' | 'standard';
  pareto_badge_fa?: string | null;
  why_this_shop_fa: string[];
  distance_km: number;
  driving_minutes: number;
  walking_minutes: number;
  latitude: number;
  longitude: number;
  address: string;
  mall_micro_guide: MallMicroGuideDto;
  is_open_now: boolean;
  today_hours_fa: string;
  last_price_changed_at?: string | null;
  freshness_badge_fa: string;
  shop_score: number;
  votes_count: number;
  has_official_warranty: boolean;
  warranty_provider?: string | null;
  has_in_person_installment: boolean;
  installment_providers: string[];
  primary_phone: string;
  is_real_torob_shop: boolean;
  instagram?: string | null;
  website_url?: string | null;
  is_category_fallback: boolean;
}

export interface RecommendedProductDto {
  product_id: string | number;
  title: string;
  english_title: string;
  category_id: number;
  category_name: string;
  brand_name?: string | null;
  image_url: string;
  min_price_toman: number;
  max_price_toman: number;
  store_count: number;
  match_score: number;
  best_for_fa: string;
  badge_fa?: string | null;
  pros_fa: string[];
  cons_fa: string[];
  specs: Record<string, string>;
}

export interface ClarificationCardDto {
  question_fa: string;
  category: string;
  category_title: string;
  clarification_round: number;
  max_rounds: number;
  options: Array<{
    option_id: string;
    label_fa: string;
    weight_deltas: Record<string, number>;
  }>;
  questions: Array<{
    id: string;
    title: string;
    question: string;
    impact_badge: string;
    icon_type: 'time' | 'location' | 'payment' | 'usage';
    options: string[];
    placeholder: string;
  }>;
}

export interface ChatTurnResponseDto {
  session_id: string;
  assistant_text: string;
  widget_type: 'store_ranking' | 'clarification' | 'comparison' | 'product_discovery';
  clarification_card?: ClarificationCardDto | null;
  recsys_state: RecSysStateDto;
  recommended_products: RecommendedProductDto[];
  stores: ScoredStoreOfferDto[];
  comparison_matrix?: {
    headers: string[];
    rows: Array<{ feature: string; values: string[] }>;
  } | null;
  follow_up_chips: string[];
}

export interface HealthResponseDto {
  status: 'ok' | 'degraded';
  postgres_pgvector_ready: boolean;
  redis_ready: boolean;
  counts: {
    shops: number;
    products: number;
    offers: number;
    real_torob_shops: number;
  };
  jev_engine_mode: 'typesafe_sdk' | 'openai_compatible_system_one';
}

export interface FallbackStoreResponseDto {
  fallback_type: 'exact_product_same_mall' | 'exact_product_nearby' | 'similar_product_nearby';
  banner_fa: string;
  alternative_store: ScoredStoreOfferDto;
}

const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env || {};
export const API_BASE = env.VITE_API_BASE_PATH || '/api/v1';
export const DEFAULT_USER_ID = env.VITE_DEFAULT_USER_ID || 'usr_tehran_default';
export const DEFAULT_USER_LAT = Number(env.VITE_DEFAULT_LAT || 35.7219);
export const DEFAULT_USER_LNG = Number(env.VITE_DEFAULT_LNG || 51.3347);
export const MAP_TILE_URL =
  env.VITE_MAP_TILE_URL || 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';

export function mapDtoToProduct(dto: RecommendedProductDto): Product {
  return {
    id: String(dto.product_id),
    title: dto.title,
    englishTitle: dto.english_title || dto.title,
    category: dto.category_name,
    brand: dto.brand_name || 'نامشخص',
    image: dto.image_url || 'https://picsum.photos/seed/torob/400/400',
    minPrice: dto.min_price_toman,
    maxPrice: dto.max_price_toman,
    storeCount: dto.store_count,
    rating: Number((dto.match_score / 20).toFixed(1)),
    pros: dto.pros_fa,
    cons: dto.cons_fa,
    specs: dto.specs,
    bestFor: dto.best_for_fa || `${dto.match_score}٪ تطابق با اولویت شما`,
    badge: dto.badge_fa || `${dto.match_score}٪ تطابق`,
  };
}

export function mapDtoToShopOffer(dto: ScoredStoreOfferDto): ShopOffer {
  const parsedTs = dto.last_price_changed_at
    ? Date.parse(dto.last_price_changed_at)
    : Date.now();
  return {
    id: String(dto.offer_id),
    productId: String(dto.product_id),
    shopId: String(dto.shop_id),
    shopName: dto.shop_name,
    isRealShop: dto.is_real_torob_shop,
    hasWebsiteOrInstagram: Boolean(dto.website_url || dto.instagram),
    websiteUrl: dto.website_url || undefined,
    instagramHandle: dto.instagram || undefined,
    mallName: dto.mall_micro_guide?.mall_name || '',
    mallFloor: dto.mall_micro_guide?.floor_label || '',
    mallUnit: dto.mall_micro_guide?.unit_label || '',
    mallNote:
      dto.mall_micro_guide?.note_fa ||
      dto.why_this_shop_fa.join(' • ') ||
      dto.address,
    neighborhood: dto.mall_micro_guide?.mall_name || 'تهران',
    address: dto.address,
    coordinates: {
      lat: dto.latitude,
      lng: dto.longitude,
    },
    distanceKm: dto.distance_km,
    estimatedDrivingMins: dto.driving_minutes,
    estimatedWalkingMins: dto.walking_minutes,
    price: dto.price_toman,
    officialListPrice: Math.round(dto.price_toman * 1.05),
    discountToman: Math.round(dto.price_toman * 0.05),
    lastUpdated: dto.freshness_badge_fa,
    lastUpdatedTimestamp: Number.isNaN(parsedTs) ? Date.now() : parsedTs,
    warranty: dto.warranty_provider || (dto.has_official_warranty ? 'گارانتی معتبر' : 'بدون گارانتی ثبت‌شده'),
    torobPayAccepted: dto.installment_providers.includes('ترب‌پی'),
    installmentOptions: dto.installment_providers,
    kallabargSupported: false,
    workingHours: dto.today_hours_fa,
    isOpenNow: dto.is_open_now,
    phone: dto.primary_phone || '02100000000',
    reputationScore: dto.shop_score,
    historyInTorobYears: Math.max(1, Math.min(8, Math.round(dto.votes_count / 15) || 2)),
    stockStatus: dto.is_category_fallback
      ? 'unconfirmed_in_catalog'
      : 'confirmed_in_stock',
    utilityScore: dto.utility_score,
    paretoRole: dto.pareto_role,
    paretoBadge: dto.pareto_badge_fa || undefined,
    whyThisShop: dto.why_this_shop_fa,
  };
}

export function mapDtoToClarification(
  dto?: ClarificationCardDto | null,
): FeatureClarificationPayload | undefined {
  if (!dto) return undefined;
  return {
    category: dto.category,
    categoryTitle: dto.category_title,
    questions: dto.questions.map((q) => ({
      id: q.id,
      title: q.title,
      question: q.question,
      impactBadge: q.impact_badge,
      iconType: q.icon_type,
      options: q.options,
      placeholder: q.placeholder,
    })),
  };
}

export async function fetchHealth(): Promise<HealthResponseDto> {
  const res = await fetch(`${API_BASE}/health`);
  if (!res.ok) throw new Error(`Health check failed: ${res.status}`);
  return res.json();
}

export async function postChatTurn(payload: {
  session_id: string;
  user_id: string;
  message: string;
  user_location: CoordinatesDto;
  ui_overrides?: UIOverridesDto;
  selected_product_id?: string | number | null;
}): Promise<ChatTurnResponseDto> {
  const res = await fetch(`${API_BASE}/chat/turn`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Chat turn failed: ${res.status}`);
  return res.json();
}

export async function postFeedback(payload: {
  session_id: string;
  user_id: string;
  feedback_type: 'clarification_choice' | 'thumbs_up' | 'thumbs_down' | 'weight_override' | 'price_discrepancy';
  selected_option_id?: string;
  clarification_answers?: Record<string, string>;
  weight_overrides?: Record<string, number>;
  user_location?: CoordinatesDto;
}): Promise<ChatTurnResponseDto> {
  const res = await fetch(`${API_BASE}/feedback`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(`Feedback update failed: ${res.status}`);
  return res.json();
}

export async function fetchFallbackStore(
  offerId: number | string,
  lat: number,
  lng: number,
  excludedShopIds: Array<number | string> = [],
): Promise<FallbackStoreResponseDto> {
  const params = new URLSearchParams({
    lat: String(lat),
    lng: String(lng),
  });
  if (excludedShopIds.length > 0) {
    params.set('excluded_shop_ids', excludedShopIds.join(','));
  }
  const res = await fetch(`${API_BASE}/stores/${offerId}/fallback?${params.toString()}`);
  if (!res.ok) throw new Error(`Fallback store lookup failed: ${res.status}`);
  return res.json();
}
