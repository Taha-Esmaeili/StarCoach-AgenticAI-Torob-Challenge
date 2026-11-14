"""Typed Pydantic schemas matching specs/001-torob-shopping-assistant/contracts/api.md and UI_Template/src/types.ts.

All default coordinates, user IDs, slot bounds, and clarification round limits are
sourced dynamically from `backend.config.settings` (.env) rather than hardcoded.
"""

from typing import Any, Literal
from pydantic import BaseModel, Field

from backend.config import settings


class Coordinates(BaseModel):
    lat: float = Field(
        default_factory=lambda: settings.default_user_lat,
        ge=settings.tehran_lat_min,
        le=settings.tehran_lat_max,
    )
    lng: float = Field(
        default_factory=lambda: settings.default_user_lng,
        ge=settings.tehran_lng_min,
        le=settings.tehran_lng_max,
    )


class UIOverrides(BaseModel):
    require_open_now: bool = False
    require_installment: bool = False
    require_warranty: bool = False
    require_torob_pay: bool = False
    max_distance_km: float | None = None
    max_price_toman: int | None = None


class ChatTurnRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    user_id: str = Field(default_factory=lambda: settings.default_user_id, min_length=1)
    message: str = Field(..., min_length=1)
    user_location: Coordinates = Field(default_factory=Coordinates)
    ui_overrides: UIOverrides = Field(default_factory=UIOverrides)
    selected_product_id: str | int | None = None


class ActiveWeightSlot(BaseModel):
    slot: int = Field(..., ge=1, le=settings.recsys_total_slots)
    key: str
    label_fa: str
    slot_group: Literal["base", "persona", "dynamic"] = "base"
    weight: float = Field(..., ge=0.0, le=1.0)
    unconstrained_weight: float = Field(default=0.5, ge=0.0, le=1.0)
    confidence: float = Field(..., ge=0.0, le=1.0)


class HardConstraintsState(BaseModel):
    require_open_now: bool = False
    require_installment: bool = False
    require_warranty: bool = False


class RecSysStatePayload(BaseModel):
    effective_confidence: float = Field(..., ge=0.0, le=1.0)
    clarification_count: int = Field(default=0, ge=0, le=settings.recsys_max_clarification_rounds)
    dissatisfaction_triggered: bool = False
    active_weights: list[ActiveWeightSlot] = Field(default_factory=list)
    hard_constraints: HardConstraintsState = Field(default_factory=HardConstraintsState)


class ClarificationOption(BaseModel):
    option_id: str
    label_fa: str
    weight_deltas: dict[str, float] = Field(default_factory=dict)


class FeatureQuestionItem(BaseModel):
    """Compatible with UI_Template FeatureQuestion interface."""

    id: str
    title: str
    question: str
    impact_badge: str
    icon_type: Literal["time", "location", "payment", "usage"] = "usage"
    options: list[str]
    placeholder: str = "توضیح دلخواه شما..."


class ClarificationCardPayload(BaseModel):
    question_fa: str
    category: str = "general"
    category_title: str = "خرید حضوری"
    clarification_round: int = Field(default=1, ge=1, le=settings.recsys_max_clarification_rounds)
    max_rounds: int = Field(default_factory=lambda: settings.recsys_max_clarification_rounds)
    options: list[ClarificationOption] = Field(default_factory=list)
    questions: list[FeatureQuestionItem] = Field(default_factory=list)


class MallMicroGuide(BaseModel):
    mall_name: str | None = None
    floor_label: str | None = None
    unit_label: str | None = None
    note_fa: str | None = None


class ScoredStoreOffer(BaseModel):
    offer_id: str | int
    product_id: str | int
    product_name: str
    shop_id: str | int
    shop_name: str
    price_toman: int
    utility_score: int = Field(..., ge=0, le=100)
    pareto_role: Literal["best_overall", "closest_open", "lowest_price", "standard"] = "standard"
    pareto_badge_fa: str | None = None
    why_this_shop_fa: list[str] = Field(default_factory=list)
    distance_km: float
    driving_minutes: int
    walking_minutes: int
    latitude: float
    longitude: float
    address: str
    mall_micro_guide: MallMicroGuide = Field(default_factory=MallMicroGuide)
    is_open_now: bool
    today_hours_fa: str
    last_price_changed_at: str | None = None
    freshness_badge_fa: str
    shop_score: float = Field(default=4.5, ge=0.0, le=5.0)
    votes_count: int = 0
    has_official_warranty: bool = False
    warranty_provider: str | None = None
    has_in_person_installment: bool = False
    installment_providers: list[str] = Field(default_factory=list)
    primary_phone: str = ""
    is_real_torob_shop: bool = False
    instagram: str | None = None
    website_url: str | None = None
    is_category_fallback: bool = False
    feature_scores: dict[str, float] = Field(default_factory=dict)


class RecommendedProductItem(BaseModel):
    product_id: str | int
    title: str
    english_title: str = ""
    category_id: int = 0
    category_name: str
    brand_name: str | None = None
    image_url: str = ""
    min_price_toman: int
    max_price_toman: int
    store_count: int
    match_score: int = Field(default=90, ge=0, le=100)
    best_for_fa: str = ""
    badge_fa: str | None = None
    pros_fa: list[str] = Field(default_factory=list)
    cons_fa: list[str] = Field(default_factory=list)
    specs: dict[str, str] = Field(default_factory=dict)


class ComparisonTableWidget(BaseModel):
    headers: list[str]
    rows: list[dict[str, str | list[str]]]


class ChatTurnResponse(BaseModel):
    session_id: str
    assistant_text: str
    widget_type: Literal["store_ranking", "clarification", "comparison", "product_discovery"] = "store_ranking"
    clarification_card: ClarificationCardPayload | None = None
    recsys_state: RecSysStatePayload
    recommended_products: list[RecommendedProductItem] = Field(default_factory=list)
    stores: list[ScoredStoreOffer] = Field(default_factory=list)
    comparison_matrix: ComparisonTableWidget | None = None
    follow_up_chips: list[str] = Field(default_factory=list)


class FeedbackRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    user_id: str = Field(default_factory=lambda: settings.default_user_id, min_length=1)
    feedback_type: Literal[
        "clarification_choice",
        "thumbs_up",
        "thumbs_down",
        "weight_override",
        "price_discrepancy",
        "location_update",
    ]
    target_offer_id: str | int | None = None
    target_product_id: str | int | None = None
    selected_option_id: str | None = None
    clarification_answers: dict[str, str] = Field(default_factory=dict)
    weight_overrides: dict[str, float] = Field(default_factory=dict)
    hard_constraints: HardConstraintsState | None = None
    user_location: Coordinates = Field(default_factory=Coordinates)


class ClosestOpenShopSummary(BaseModel):
    shop_id: str | int
    shop_name: str
    distance_km: float
    price_toman: int
    mall_badge_fa: str | None = None


class ComparedModelEntry(BaseModel):
    product_id: str | int
    name: str
    brand_name: str | None = None
    image_url: str = ""
    min_in_person_price_toman: int
    open_stores_count: int
    closest_open_shop: ClosestOpenShopSummary | None = None
    specs: dict[str, str] = Field(default_factory=dict)
    pros_fa: list[str] = Field(default_factory=list)
    cons_fa: list[str] = Field(default_factory=list)


class CompareProductsResponse(BaseModel):
    category_name: str
    spec_keys: list[str]
    models: list[ComparedModelEntry]


class FallbackStoreResponse(BaseModel):
    fallback_type: Literal["exact_product_same_mall", "exact_product_nearby", "similar_product_nearby"]
    banner_fa: str
    alternative_store: ScoredStoreOffer


class DatasetCounts(BaseModel):
    shops: int = 0
    products: int = 0
    offers: int = 0
    real_torob_shops: int = 0


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    postgres_pgvector_ready: bool = False
    redis_ready: bool = False
    counts: DatasetCounts = Field(default_factory=DatasetCounts)
    jev_engine_mode: Literal["typesafe_sdk", "openai_compatible_system_one"] = "openai_compatible_system_one"


class SessionSummaryItem(BaseModel):
    session_id: str
    title: str
    active_category_name: str | None = None
    updated_at: str
    turn_count: int = 1


class UserSessionsListResponse(BaseModel):
    user_id: str
    sessions: list[SessionSummaryItem] = Field(default_factory=list)


class SessionHistoryDetailResponse(BaseModel):
    session_id: str
    user_id: str
    title: str
    active_category_name: str | None = None
    selected_product_id: str | None = None
    updated_at: str
    require_torob_pay: bool = False
    hard_constraints: HardConstraintsState = Field(default_factory=HardConstraintsState)
    active_weights: list[ActiveWeightSlot] = Field(default_factory=list)
    ui_turns: list[dict[str, Any]] = Field(default_factory=list)


class DeleteSessionResponse(BaseModel):
    session_id: str
    deleted: bool = True
