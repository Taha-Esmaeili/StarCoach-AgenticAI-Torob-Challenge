"""FastAPI application entrypoint for Torob Smart In-Person Shopping Assistant (ترب‌چیت حضوری)."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import asyncpg
import redis.asyncio as aioredis
from fastapi import BackgroundTasks, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import settings
from backend.db.normalizer import (
    canonicalize_spec_map,
    normalize_persian_text,
    to_persian_digits,
)
from backend.db.postgres import ensure_schema
from backend.db.profiles import (
    fetch_user_traits,
    load_shopping_session,
    load_user_profile,
    save_shopping_session,
    save_user_profile,
)
from backend.db.queries import (
    extract_search_tokens,
    fetch_candidate_categories,
    fetch_candidate_offers,
    fetch_fallback_store,
    fetch_product_by_id,
    fetch_product_comparison,
    search_products,
)
from backend.models.schemas import (
    ChatTurnRequest,
    ChatTurnResponse,
    ClosestOpenShopSummary,
    ComparedModelEntry,
    CompareProductsResponse,
    ComparisonTableWidget,
    DatasetCounts,
    FallbackStoreResponse,
    FeedbackRequest,
    HardConstraintsState,
    HealthResponse,
    RecommendedProductItem,
    RecSysStatePayload,
)
from backend.recsys.clarifier import (
    build_clarification_card,
    should_trigger_clarification,
)
from backend.recsys.deduplicator import sync_user_traits
from backend.recsys.jev_engine import (
    ExtractedTrait,
    ScoreJudgment,
    evaluate_turn_with_jev,
    score_candidate_products_with_decision_model,
    score_custom_offer_criterion_with_decision_model,
)
from backend.recsys.scorer import score_and_rank_offers, score_and_rank_offers_with_meta
from backend.recsys.weights import (
    fuse_and_normalize_weights,
    l1_normalize_weights,
    update_category_price_percentile,
    update_store_weights_contrastive,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage PostgreSQL (`asyncpg`) and Redis (`redis.asyncio`) connection pools configured via .env."""
    app.state.pg_pool = None
    app.state.redis = None

    try:
        app.state.pg_pool = await asyncpg.create_pool(
            dsn=settings.asyncpg_dsn,
            min_size=settings.postgres_pool_min_size,
            max_size=settings.postgres_pool_max_size,
            command_timeout=settings.postgres_command_timeout_seconds,
        )
        await ensure_schema(app.state.pg_pool)
    except Exception:
        # shortcut: allow app startup before docker-compose / DB ingestion runs; health endpoint reports postgres_pgvector_ready=False
        app.state.pg_pool = None

    try:
        redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=settings.redis_socket_timeout_seconds,
        )
        await redis_client.ping()
        app.state.redis = redis_client
    except Exception:
        app.state.redis = None

    yield

    if getattr(app.state, "pg_pool", None) is not None:
        await app.state.pg_pool.close()
    if getattr(app.state, "redis", None) is not None:
        await app.state.redis.aclose()


app = FastAPI(
    title="Torob Smart In-Person Shopping Assistant API (ترب‌چیت حضوری)",
    version="0.3.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def _probe_postgres_counts(pg_pool: Any) -> tuple[bool, DatasetCounts]:
    if pg_pool is None:
        return False, DatasetCounts()
    try:
        async with pg_pool.acquire() as conn:
            has_vector = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector');"
            )
            has_shops = await conn.fetchval("SELECT to_regclass('public.shops') IS NOT NULL;")
            if not has_shops:
                return bool(has_vector), DatasetCounts()

            row = await conn.fetchrow(
                """
                SELECT
                    (SELECT COUNT(*) FROM shops) AS shops_count,
                    (SELECT COUNT(*) FROM products) AS products_count,
                    (SELECT COUNT(*) FROM offers) AS offers_count,
                    (SELECT COUNT(*) FROM shops WHERE is_real_torob_shop = TRUE) AS real_shops_count
                """
            )
            counts = DatasetCounts(
                shops=int(row["shops_count"] or 0),
                products=int(row["products_count"] or 0),
                offers=int(row["offers_count"] or 0),
                real_torob_shops=int(row["real_shops_count"] or 0),
            )
            return bool(has_vector), counts
    except Exception:
        return False, DatasetCounts()


async def _probe_redis(redis_client: Any) -> bool:
    if redis_client is None:
        return False
    try:
        return bool(await redis_client.ping())
    except Exception:
        return False


def _merge_active_traits(
    extracted: list[ExtractedTrait],
    transferred: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Combine explicit current-turn traits with compatible transferred traits without axis collision."""
    merged: list[dict[str, Any]] = []
    seen_aspects: set[str] = set()
    for t in extracted:
        norm_a = normalize_persian_text(t.aspect)
        if norm_a and norm_a not in seen_aspects:
            seen_aspects.add(norm_a)
            merged.append({"aspect": t.aspect, "preference": t.preference, "is_durable": t.is_durable})
    for tr in transferred:
        norm_a = normalize_persian_text(str(tr.get("aspect") or ""))
        if norm_a and norm_a not in seen_aspects:
            seen_aspects.add(norm_a)
            merged.append({"aspect": str(tr["aspect"]), "preference": str(tr["preference"]), "transferred": True})
    return merged[: settings.recsys_max_traits_per_query]


def _build_recommended_product_cards(
    raw_products: list[dict[str, Any]],
) -> list[RecommendedProductItem]:
    """Build UI product cards strictly honoring Decision-Model verified `matched_traits` (`0%` false badges)."""
    cards: list[RecommendedProductItem] = []
    for idx, p in enumerate(raw_products):
        min_p = int(p.get("min_price_toman") or 0)
        max_p = int(p.get("max_price_toman") or min_p)
        sc = int(p.get("store_count") or 1)
        dec_score = p.get("decision_score")
        if dec_score is not None:
            match_score = max(72, min(98, int(round(66 + float(dec_score) * 32))))
        else:
            sim = float(p.get("trgm_sim") or 0.75)
            match_score = max(78, min(98, int(round(82 + sim * 16 - idx * 2))))
        if p.get("is_stock_or_copy"):
            badge = "کالای استوک / غیراصلی"
        elif idx == 0:
            badge = "پیشنهاد اول ترب‌چیت"
        elif idx == 1:
            badge = "ارزش خرید بالا"
        else:
            badge = f"{to_persian_digits(match_score)}٪ تطابق"
        min_p_fmt = to_persian_digits(f"{min_p:,}")
        sc_fmt = to_persian_digits(sc)
        specs_dict = canonicalize_spec_map(p.get("specs"))
        spec_highlights = [f"{k}: {v}" for k, v in list(specs_dict.items())[:2]]
        matched_traits = [str(t).strip() for t in (p.get("matched_traits") or []) if str(t).strip()]
        trait_suffix = (
            f" • هماهنگ با سلیقه شما ({'، '.join(matched_traits)})"
            if matched_traits
            else ""
        )
        best_for = (
            f"موجود در {sc_fmt} فروشگاه حضوری تهران با کف قیمت {min_p_fmt} تومان"
            + (f" ({' • '.join(spec_highlights)})" if spec_highlights else "")
            + trait_suffix
        )
        pros_list = [
            f"موجود در {sc_fmt} فروشگاه حضوری تهران",
            f"شروع قیمت حضوری از {min_p_fmt} تومان",
            *(
                [f"منطبق با ترجیح شما: {matched_traits[0]}"]
                if matched_traits
                else (spec_highlights[:1] if spec_highlights else ["امکان بررسی حضوری پیش از خرید"])
            ),
        ]
        cards.append(
            RecommendedProductItem(
                product_id=str(p["product_id"]),
                title=str(p["title"]),
                english_title=str(p.get("english_title") or p["title"]),
                category_id=int(p.get("category_id") or 1),
                category_name=str(p.get("category_name") or "محصولات منتخب"),
                brand_name=p.get("brand_name"),
                image_url=str(p.get("image_url") or ""),
                min_price_toman=min_p,
                max_price_toman=max_p,
                store_count=sc,
                match_score=match_score,
                best_for_fa=best_for,
                badge_fa=badge,
                pros_fa=pros_list,
                cons_fa=["نیازمند هماهنگی تلفنی موجودی پیش از حرکت"],
                specs=specs_dict,
            )
        )
    return cards


def _format_distinct_comparison_header(title: str, max_len: int = 56) -> str:
    clean = " ".join(str(title or "").split())
    if len(clean) <= max_len:
        return clean
    if clean.endswith(")") and "(" in clean:
        paren_idx = clean.rfind("(")
        suffix = clean[paren_idx:]
        if len(suffix) <= 22:
            head_budget = max(18, max_len - len(suffix) - 2)
            return f"{clean[:head_budget].rstrip()}… {suffix}"
    return f"{clean[: max_len - 1].rstrip()}…"


def _build_inline_comparison_matrix(cards: list[RecommendedProductItem]) -> ComparisonTableWidget | None:
    if len(cards) < 2:
        return None
    top_cards = cards[:3]
    col_headers: list[str] = []
    for idx, c in enumerate(top_cards):
        h = _format_distinct_comparison_header(c.title)
        if h in col_headers:
            tail = c.title[-18:].strip()
            h = f"{h} ({tail})" if tail and tail not in h else f"{h} (#{to_persian_digits(idx + 1)})"
        col_headers.append(h)
    headers = ["ویژگی / مشخصات", *col_headers]
    rows: list[dict[str, str | list[str]]] = [
        {
            "feature": "کف قیمت حضوری تهران",
            "values": [f"{to_persian_digits(f'{c.min_price_toman:,}')} تومان" for c in top_cards],
        },
        {
            "feature": "تعداد فروشگاه حضوری",
            "values": [f"{to_persian_digits(c.store_count)} فروشگاه" for c in top_cards],
        },
    ]
    seen_keys: list[str] = []
    canon_specs_list = [canonicalize_spec_map(c.specs) for c in top_cards]
    for cs in canon_specs_list:
        for k in cs:
            if k not in seen_keys and len(seen_keys) < 4:
                seen_keys.append(k)
    for k in seen_keys:
        rows.append(
            {
                "feature": k,
                "values": [cs.get(k, "—") for cs in canon_specs_list],
            }
        )
    return ComparisonTableWidget(headers=headers, rows=rows)


def _compose_assistant_summary_fa(
    query: str,
    products: list[RecommendedProductItem],
    stores: list[Any],
    clarification_triggered: bool,
    dissatisfaction_triggered: bool,
    category_name: str | None = None,
    preview_candidates: list[dict[str, Any]] | None = None,
    unmet_constraints_fa: list[str] | None = None,
) -> str:
    if dissatisfaction_triggered:
        return (
            "متوجه شدم پیشنهادهای قبلی دقیقاً مطابق سلیقه یا شرایط شما نبود. "
            "لطفاً در فرم زیر مشخص کنید کدام معیار (قیمت، مسافت، یا پرداخت اقساطی) برایتان اولویت بالاتری دارد تا پیشنهادهای دقیق را برایتان آماده کنم:"
        )
    if clarification_triggered:
        cat_name = category_name or (products[0].category_name if products else "محصول مورد نظر")
        previews = preview_candidates or []
        if previews:
            bullet_lines = []
            for p in previews[:3]:
                p_min = to_persian_digits(f"{int(p.get('min_price_toman') or 0):,}")
                p_sc = to_persian_digits(int(p.get("store_count") or 1))
                bullet_lines.append(
                    f"- **{p['title']}** (شروع از {p_min} تومان در {p_sc} فروشگاه)"
                )
            items_block = "\n".join(bullet_lines)
            return (
                f"بر اساس جستجو در بازار حضوری تهران در دستهٔ **«{cat_name}»**، این گزینه‌های مرتبط موجود هستند:\n\n"
                f"{items_block}\n\n"
                "این‌ها در فروشگاه‌های تهران موجودند؛ ولی **برای این‌که دقیق‌تر باشیم**، در فرم زیر بهم بگو کدوم برات اولویت داره: "
                "**اونی که بهت نزدیک‌تره و همین الان بازه**، **اونی که ارزان‌تره**، یا **خرید قسطی حضوری (ترب‌پی/اسنپ‌پی) و فروشگاه معتبر** تا دقیق‌ترین پیشنهادها رو برات بیارم:"
            )
        return (
            f"برای اینکه بهترین گزینه و مناسب‌ترین فروشگاه حضوری **«{cat_name}»** را در تهران دقیقاً مطابق شرایطتان پیدا کنم، "
            "لطفاً ابتدا در فرم زیر مشخص کنید کدام مورد برایتان مهم‌تر است تا سراغ آیتم‌های دقیق‌تر برویم:"
        )
    if not products and not stores:
        return f"برای عبارت «{query}» در حال حاضر پیشنهاد حضوری مستقیمی یافت نشد. لطفاً نام دقیق‌تر مدل یا دسته‌بندی کالا را وارد کنید."

    top_prod = products[0] if products else None
    top_store = stores[0] if stores else None
    lines: list[str] = []
    if unmet_constraints_fa:
        joined_unmet = "، ".join(dict.fromkeys(unmet_constraints_fa))
        lines.append(
            f"⚠️ در حال حاضر هیچ فروشگاهی با شرط **«{joined_unmet}»** یافت نشد، اما اگر این شرط را بردارید این موارد موجود هستند:"
        )
    if top_prod:
        lines.append(
            f"بر اساس بررسی **{to_persian_digits(len(products))} گزینه برتر** در دسته **«{top_prod.category_name}»**، "
            f"بهترین انتخاب فعلی **{top_prod.title}** با کف قیمت حضوری **{to_persian_digits(f'{top_prod.min_price_toman:,}')} تومان** در **{to_persian_digits(top_prod.store_count)} فروشگاه تهران** است."
        )
    if top_store:
        mall_part = (
            f" ({top_store.mall_micro_guide.note_fa})"
            if top_store.mall_micro_guide and top_store.mall_micro_guide.note_fa
            else ""
        )
        price_part = (
            f" با قیمت **{to_persian_digits(f'{int(top_store.price_toman):,}')} تومان**،"
            if int(top_store.price_toman or 0) > 0
            else ""
        )
        lines.append(
            f"- **بهترین فروشگاه پیشنهادی**: **{top_store.shop_name}**{mall_part}{price_part} فاصله **{to_persian_digits(top_store.distance_km)} کیلومتر** و امتیاز مطلوبیت **{to_persian_digits(top_store.utility_score)}٪**."
        )
    return "\n\n".join(lines)


def _extract_category_price_span(raw_products: list[dict[str, Any]]) -> dict[str, int]:
    if not raw_products:
        return {}
    p10 = int(raw_products[0].get("category_p10_price") or 0)
    p90 = int(raw_products[0].get("category_p90_price") or 0)
    if p10 <= 0 or p90 <= p10:
        prices = [int(p.get("min_price_toman") or 0) for p in raw_products if int(p.get("min_price_toman") or 0) > 0]
        if prices:
            p10 = min(prices)
            p90 = max(prices)
    return {"p10": p10, "p90": p90} if p90 > 0 else {}


@app.get(f"{settings.api_v1_prefix}/health", response_model=HealthResponse)
async def get_health(request: Request) -> HealthResponse:
    """Liara readiness and PostgreSQL + pgvector + Redis dataset integrity probe."""
    pg_ready, counts = await _probe_postgres_counts(getattr(request.app.state, "pg_pool", None))
    redis_ready = await _probe_redis(getattr(request.app.state, "redis", None))
    overall_status = "ok" if (pg_ready and redis_ready) else "degraded"
    return HealthResponse(
        status=overall_status,
        postgres_pgvector_ready=pg_ready,
        redis_ready=redis_ready,
        counts=counts,
        jev_engine_mode=settings.jev_engine_mode,
    )


@app.post(f"{settings.api_v1_prefix}/chat/turn", response_model=ChatTurnResponse)
async def post_chat_turn(
    req: ChatTurnRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> ChatTurnResponse:
    """Execute a full conversational shopping turn powered by the Clean Two-Layer Adaptive Jev RecSys."""
    pg_pool = getattr(request.app.state, "pg_pool", None)
    redis_client = getattr(request.app.state, "redis", None)

    user_profile = await load_user_profile(req.user_id, pg_pool=pg_pool, redis_client=redis_client)
    session = await load_shopping_session(
        req.session_id,
        user_id=req.user_id,
        lat=req.user_location.lat,
        lng=req.user_location.lng,
        pg_pool=pg_pool,
        redis_client=redis_client,
    )
    stored_traits = await fetch_user_traits(
        pg_pool,
        user_id=req.user_id,
        limit=settings.recsys_max_stored_traits_per_user,
    )

    cat_query = f"{session.get('product_search_query') or ''} {req.message}".strip()
    cand_cats = await fetch_candidate_categories(pg_pool, cat_query, limit=10)
    try:
        eval_res = await evaluate_turn_with_jev(
            req.message,
            session_context=session,
            candidate_categories=cand_cats,
            stored_user_traits=stored_traits,
            stored_price_priors=user_profile.get("price_percentiles"),
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    is_gift_turn = eval_res.is_ephemeral_or_gift.noul >= settings.recsys_ephemeral_gift_noul_threshold
    active_traits = _merge_active_traits(eval_res.extracted_traits, eval_res.transferred_traits)
    custom_criterion = eval_res.custom_offer_criterion.strip()
    include_custom = bool(custom_criterion)

    merged_session_weights = dict(eval_res.session_weights)
    if eval_res.is_continuation:
        mention_thresh = settings.recsys_mention_score_threshold
        for k, raw_prev in (session.get("session_weights") or {}).items():
            if not isinstance(raw_prev, dict):
                continue
            prev_score = float(raw_prev.get("score", 0.0))
            prev_conf = float(raw_prev.get("confidence", 0.85))
            cur_j = merged_session_weights.get(k)
            if prev_score >= mention_thresh and (cur_j is None or cur_j.score < mention_thresh):
                merged_session_weights[k] = ScoreJudgment(score=prev_score, confidence=prev_conf)

    # Layer-2 Sparse Override Fusion + L1 Normalization (`5 + 1` store slots; chat turns never mutate user_profile)
    active_slots, l1_weights, eff_conf = fuse_and_normalize_weights(
        user_profile,
        merged_session_weights,
        include_custom_offer=include_custom,
        custom_offer_label_fa=(f"شرط خاص: {custom_criterion[:24]}" if include_custom else None),
    )

    hurdle_thresh = settings.recsys_dealbreaker_noul_threshold
    prev_hard = dict(session.get("hard_constraints") or {}) if eval_res.is_continuation else {}
    req_torob_pay = bool(
        req.ui_overrides.require_torob_pay
        or (bool(session.get("require_torob_pay")) if eval_res.is_continuation else False)
        or eval_res.require_torob_pay
    )
    hard_constraints = HardConstraintsState(
        require_open_now=bool(
            req.ui_overrides.require_open_now
            or prev_hard.get("require_open_now", False)
            or eval_res.dealbreakers["require_open_now"].noul >= hurdle_thresh
        ),
        require_installment=bool(
            req.ui_overrides.require_installment
            or req_torob_pay
            or prev_hard.get("require_installment", False)
            or eval_res.dealbreakers["require_installment"].noul >= hurdle_thresh
        ),
        require_warranty=bool(
            req.ui_overrides.require_warranty
            or prev_hard.get("require_warranty", False)
            or eval_res.dealbreakers["require_warranty"].noul >= hurdle_thresh
        ),
    )

    clarify_count = int(session.get("clarification_count", 0))
    should_ask, next_clarify_count = should_trigger_clarification(
        effective_confidence=eff_conf,
        clarification_count=clarify_count,
        explicit_thumbs_down=False,
        dissatisfied_noul=eval_res.user_dissatisfied.noul,
        needs_clarification_noul=eval_res.needs_clarification.noul,
        intent_choice=eval_res.intent_choice.choice,
        is_continuation=eval_res.is_continuation,
    )
    if req.selected_product_id:
        should_ask = False
        next_clarify_count = clarify_count
    dissatisfaction_triggered = bool(should_ask and clarify_count >= 1)

    min_price = eval_res.min_price_toman
    max_price = req.ui_overrides.max_price_toman or eval_res.max_price_toman
    max_dist = req.ui_overrides.max_distance_km or eval_res.max_distance_km
    clean_search_query = eval_res.product_search_query or req.message
    catalog_terms = eval_res.catalog_search_terms
    price_tier = eval_res.price_tier
    cat_keywords = eval_res.category_keywords
    is_acc_req = eval_res.is_accessory_request
    wants_used = eval_res.wants_used_or_stock

    rej_offers = list(session.get("rejected_offer_ids") or []) if eval_res.is_continuation else []
    rej_shops = list(session.get("rejected_shop_ids") or []) if eval_res.is_continuation else []
    rej_prods = list(session.get("rejected_product_ids") or []) if eval_res.is_continuation else []

    raw_products: list[dict[str, Any]] = []
    raw_offers: list[dict[str, Any]] = []
    product_cards: list[RecommendedProductItem] = []
    scored_stores: list[Any] = []
    unmet_labels: list[str] = []
    comp_matrix: ComparisonTableWidget | None = None
    cat_probe: list[dict[str, Any]] = []
    price_span: dict[str, int] = {}

    cumulative_request = " — ".join(
        [p for p in (clean_search_query, " ، ".join(catalog_terms[:4]), req.message) if p]
    )

    if should_ask:
        if pg_pool is not None:
            cat_probe = await search_products(
                pg_pool,
                query=clean_search_query,
                min_price_toman=min_price,
                max_price_toman=max_price,
                price_tier=price_tier,
                category_keywords=cat_keywords,
                is_accessory_request=is_acc_req,
                catalog_search_terms=catalog_terms,
                excluded_product_ids=rej_prods,
                limit=6,
                redis_client=redis_client,
            )
            price_span = _extract_category_price_span(cat_probe)
            active_cat = (
                str(cat_probe[0]["category_name"])
                if cat_probe
                else (session.get("active_category_name") or "محصولات منتخب")
            )
            if cat_probe:
                try:
                    cat_probe = await score_candidate_products_with_decision_model(
                        user_message=cumulative_request,
                        candidates=cat_probe,
                        active_traits=active_traits,
                        max_price_toman=max_price,
                        min_price_toman=min_price,
                        price_tier=price_tier,
                        inferred_price_percentile=eval_res.inferred_price_percentile,
                        limit=3,
                        is_accessory_request=is_acc_req,
                        wants_used_or_stock=wants_used,
                    )
                    if (
                        max_price
                        and not is_acc_req
                        and not any(p.get("is_core_device", True) for p in cat_probe)
                    ):
                        relaxed_probe = await search_products(
                            pg_pool,
                            query=clean_search_query,
                            min_price_toman=min_price,
                            max_price_toman=None,
                            price_tier="budget",
                            category_keywords=cat_keywords,
                            is_accessory_request=is_acc_req,
                            catalog_search_terms=catalog_terms,
                            excluded_product_ids=rej_prods,
                            limit=6,
                            redis_client=redis_client,
                        )
                        if relaxed_probe:
                            cat_probe = await score_candidate_products_with_decision_model(
                                user_message=cumulative_request,
                                candidates=relaxed_probe,
                                active_traits=active_traits,
                                max_price_toman=None,
                                min_price_toman=min_price,
                                price_tier="budget",
                                inferred_price_percentile=eval_res.inferred_price_percentile,
                                limit=3,
                                is_accessory_request=is_acc_req,
                                wants_used_or_stock=wants_used,
                            )
                    cat_probe = [
                        p for p in cat_probe
                        if p.get("is_core_device", True) or float(p.get("decision_score") or 0.0) >= 0.15
                    ]
                except RuntimeError:
                    cat_probe = cat_probe[:3]
        else:
            active_cat = session.get("active_category_name") or "محصولات منتخب"
    else:
        if pg_pool is not None:
            raw_products = await search_products(
                pg_pool,
                query=clean_search_query,
                min_price_toman=min_price,
                max_price_toman=max_price,
                price_tier=price_tier,
                category_keywords=cat_keywords,
                is_accessory_request=is_acc_req,
                catalog_search_terms=catalog_terms,
                excluded_product_ids=rej_prods,
                limit=8,
                redis_client=redis_client,
            )
            price_span = _extract_category_price_span(raw_products)
            budget_was_relaxed = any(bool(p.get("budget_relaxed")) for p in raw_products)
            try:
                raw_products = await score_candidate_products_with_decision_model(
                    user_message=cumulative_request,
                    candidates=raw_products,
                    active_traits=active_traits,
                    max_price_toman=max_price,
                    min_price_toman=min_price,
                    price_tier=price_tier,
                    inferred_price_percentile=eval_res.inferred_price_percentile,
                    limit=4,
                    is_accessory_request=is_acc_req,
                    wants_used_or_stock=wants_used,
                )
                # If tight budget only surfaced spare parts or counterfeit clones, relax budget to retrieve genuine complete products
                if (
                    max_price
                    and not budget_was_relaxed
                    and not is_acc_req
                    and not any(
                        p.get("is_core_device", True) and (wants_used or not p.get("is_stock_or_copy", False))
                        for p in raw_products
                    )
                ):
                    relaxed_candidates = await search_products(
                        pg_pool,
                        query=clean_search_query,
                        min_price_toman=min_price,
                        max_price_toman=None,
                        price_tier="budget",
                        category_keywords=cat_keywords,
                        is_accessory_request=is_acc_req,
                        catalog_search_terms=catalog_terms,
                        excluded_product_ids=rej_prods,
                        limit=8,
                        redis_client=redis_client,
                    )
                    if relaxed_candidates:
                        scored_relaxed = await score_candidate_products_with_decision_model(
                            user_message=cumulative_request,
                            candidates=relaxed_candidates,
                            active_traits=active_traits,
                            max_price_toman=None,
                            min_price_toman=min_price,
                            price_tier="budget",
                            inferred_price_percentile=eval_res.inferred_price_percentile,
                            limit=4,
                            is_accessory_request=is_acc_req,
                            wants_used_or_stock=wants_used,
                        )
                        if any(p.get("is_core_device", True) for p in scored_relaxed):
                            raw_products = scored_relaxed
                            budget_was_relaxed = True
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

            # Synchronize `selected_product_id` so `product_cards[0]` and `assistant_text` match `stores` 100%
            if req.selected_product_id:
                sel_id = str(req.selected_product_id)
                matching_existing = [p for p in raw_products if str(p.get("product_id")) == sel_id]
                others = [p for p in raw_products if str(p.get("product_id")) != sel_id]
                if matching_existing:
                    raw_products = [matching_existing[0], *others][:4]
                else:
                    sel_prod = await fetch_product_by_id(pg_pool, sel_id)
                    if sel_prod is not None:
                        raw_products = [sel_prod, *others][:4]

            target_pids = (
                [str(req.selected_product_id)]
                if req.selected_product_id
                else [str(p["product_id"]) for p in raw_products[:3]]
            )
            cat_name = str(raw_products[0]["category_name"]) if raw_products else session.get("active_category_name")
            raw_offers = await fetch_candidate_offers(
                pg_pool,
                product_ids=target_pids,
                user_lat=req.user_location.lat,
                user_lng=req.user_location.lng,
                category_name=cat_name,
                max_price_toman=max_price,
                redis_client=redis_client,
                require_installment=hard_constraints.require_installment,
                require_torob_pay=req_torob_pay,
                require_warranty=hard_constraints.require_warranty,
                max_distance_km=max_dist,
                excluded_offer_ids=rej_offers,
                excluded_shop_ids=rej_shops,
            )
            if include_custom and raw_offers:
                try:
                    raw_offers = await score_custom_offer_criterion_with_decision_model(
                        custom_criterion,
                        raw_offers,
                    )
                except RuntimeError as exc:
                    raise HTTPException(status_code=503, detail=str(exc)) from exc
            if budget_was_relaxed and max_price:
                unmet_labels.append(f"سقف بودجه {to_persian_digits(f'{int(max_price):,}')} تومان")

        product_cards = _build_recommended_product_cards(raw_products)
        scored_stores, store_unmet = score_and_rank_offers_with_meta(
            raw_offers,
            l1_weights=l1_weights,
            hard_constraints=hard_constraints,
            max_distance_km=max_dist,
            require_torob_pay=req_torob_pay,
            max_price_toman=max_price,
            wants_used_or_stock=wants_used,
        )
        for ul in store_unmet:
            if ul not in unmet_labels:
                unmet_labels.append(ul)
        comp_matrix = _build_inline_comparison_matrix(product_cards)
        active_cat = (
            product_cards[0].category_name
            if product_cards
            else (session.get("active_category_name") or "محصولات منتخب")
        )

    # Outlier-safe async background trait stabilization (`alpha = 0.15` soft step; blocked completely on gift turns)
    if eval_res.extracted_traits and not is_gift_turn:
        background_tasks.add_task(
            sync_user_traits,
            req.user_id,
            active_cat,
            eval_res.extracted_traits,
            pg_pool,
            is_gift_turn,
            settings.recsys_trait_soft_step,
        )

    clarification_card = (
        build_clarification_card(
            active_cat,
            next_clarify_count,
            custom_questions=eval_res.clarification_questions,
        )
        if should_ask
        else None
    )

    if should_ask:
        widget_type = "clarification"
    elif eval_res.intent_choice.choice == "comparison" and comp_matrix is not None:
        widget_type = "comparison"
    else:
        widget_type = "store_ranking"

    assistant_text = _compose_assistant_summary_fa(
        query=req.message,
        products=product_cards,
        stores=scored_stores,
        clarification_triggered=should_ask,
        dissatisfaction_triggered=dissatisfaction_triggered,
        category_name=active_cat,
        preview_candidates=cat_probe,
        unmet_constraints_fa=unmet_labels,
    )

    session["last_query"] = req.message
    session["product_search_query"] = clean_search_query
    session["catalog_search_terms"] = catalog_terms
    session["category_keywords"] = cat_keywords
    session["is_accessory_request"] = is_acc_req
    session["wants_used_or_stock"] = wants_used
    session["is_ephemeral_or_gift"] = is_gift_turn
    session["custom_offer_criterion"] = custom_criterion
    session["clarification_questions"] = eval_res.clarification_questions
    session["active_session_traits"] = [
        {"aspect": t.aspect, "preference": t.preference, "is_durable": t.is_durable}
        for t in eval_res.extracted_traits
    ]
    session["transferred_traits"] = eval_res.transferred_traits
    session["price_tier"] = price_tier
    session["min_price_toman"] = min_price
    session["max_price_toman"] = max_price
    session["max_distance_km"] = max_dist
    session["require_torob_pay"] = req_torob_pay
    session["rejected_offer_ids"] = rej_offers
    session["rejected_shop_ids"] = rej_shops
    session["rejected_product_ids"] = rej_prods
    if price_span:
        session["category_price_span"] = price_span
    session["active_category_name"] = active_cat
    session["selected_product_id"] = (
        str(req.selected_product_id)
        if req.selected_product_id
        else (product_cards[0].product_id if product_cards else session.get("selected_product_id"))
    )
    if product_cards:
        session["recommended_products"] = [p.model_dump() for p in product_cards]
    session["session_weights"] = {
        k: {"score": v.score, "confidence": v.confidence}
        for k, v in merged_session_weights.items()
    }
    session["shown_store_features"] = {
        str(s.offer_id): {
            "feature_scores": dict(s.feature_scores),
            "price_toman": int(s.price_toman),
            "product_id": str(s.product_id),
            "shop_id": str(s.shop_id),
        }
        for s in scored_stores
    }
    session["effective_weights"] = l1_weights
    session["hard_constraints"] = hard_constraints.model_dump()
    session["clarification_count"] = next_clarify_count
    session["dissatisfaction_triggered"] = dissatisfaction_triggered
    session_msgs = list(session.get("messages") or [])
    session_msgs.append({"role": "user", "text": req.message})
    session_msgs.append({"role": "assistant", "text": assistant_text})
    session["messages"] = session_msgs[-20:]

    await save_shopping_session(session, pg_pool=pg_pool, redis_client=redis_client)

    follow_up_chips = (
        []
        if should_ask
        else [
            f"نزدیک‌ترین مغازه باز برای {active_cat}",
            f"خرید قسطی حضوری با ترب‌پی در {active_cat}",
            f"ارزان‌ترین فروشگاه {active_cat} در تهران",
        ]
    )

    return ChatTurnResponse(
        session_id=req.session_id,
        assistant_text=assistant_text,
        widget_type=widget_type,
        clarification_card=clarification_card,
        recsys_state=RecSysStatePayload(
            effective_confidence=eff_conf,
            clarification_count=next_clarify_count,
            dissatisfaction_triggered=dissatisfaction_triggered,
            active_weights=active_slots,
            hard_constraints=hard_constraints,
        ),
        recommended_products=product_cards,
        stores=scored_stores,
        comparison_matrix=comp_matrix,
        follow_up_chips=follow_up_chips,
    )


@app.post(f"{settings.api_v1_prefix}/feedback", response_model=ChatTurnResponse)
@app.post(f"{settings.api_v1_prefix}/feedback/", response_model=ChatTurnResponse, include_in_schema=False)
async def post_feedback(
    req: FeedbackRequest,
    request: Request,
    background_tasks: BackgroundTasks,
) -> ChatTurnResponse:
    """Process clarification choices, 👍/👎 feedback, or slider overrides with strict consolidation safety."""
    pg_pool = getattr(request.app.state, "pg_pool", None)
    redis_client = getattr(request.app.state, "redis", None)

    user_profile = await load_user_profile(req.user_id, pg_pool=pg_pool, redis_client=redis_client)
    user_lat = req.user_location.lat if req.user_location else None
    user_lng = req.user_location.lng if req.user_location else None
    session = await load_shopping_session(
        req.session_id,
        user_id=req.user_id,
        lat=user_lat,
        lng=user_lng,
        pg_pool=pg_pool,
        redis_client=redis_client,
    )

    last_query = str(
        session.get("last_query")
        or session.get("product_search_query")
        or session.get("active_category_name")
        or ""
    )
    clean_search_query = str(session.get("product_search_query") or last_query)
    catalog_terms: list[str] = list(session.get("catalog_search_terms") or [])
    cat_keywords: list[str] = list(session.get("category_keywords") or [])
    is_acc_req = bool(session.get("is_accessory_request") or False)
    wants_used = bool(session.get("wants_used_or_stock") or False)
    is_gift_session = bool(session.get("is_ephemeral_or_gift") or False)
    custom_criterion = str(session.get("custom_offer_criterion") or "").strip()
    saved_price_tier = str(session.get("price_tier") or "mid")
    saved_min_price = session.get("min_price_toman")
    min_price = int(saved_min_price) if isinstance(saved_min_price, (int, float)) and saved_min_price > 0 else None
    saved_max_price = session.get("max_price_toman")
    max_price = int(saved_max_price) if isinstance(saved_max_price, (int, float)) and saved_max_price > 0 else None
    saved_max_dist = session.get("max_distance_km")
    max_dist = float(saved_max_dist) if isinstance(saved_max_dist, (int, float)) and float(saved_max_dist) > 0 else None
    req_torob_pay = bool(session.get("require_torob_pay") or False)
    rej_offers: list[str] = [str(x) for x in (session.get("rejected_offer_ids") or []) if x]
    rej_shops: list[str] = [str(x) for x in (session.get("rejected_shop_ids") or []) if x]
    rej_prods: list[str] = [str(x) for x in (session.get("rejected_product_ids") or []) if x]

    hard_raw = dict(session.get("hard_constraints") or {})
    if req.hard_constraints is not None:
        hard_raw.update(req.hard_constraints.model_dump())

    session_judgments: dict[str, ScoreJudgment] = {}
    for k, raw_j in (session.get("session_weights") or {}).items():
        if isinstance(raw_j, dict):
            session_judgments[k] = ScoreJudgment(
                score=float(raw_j.get("score", 0.0)),
                confidence=float(raw_j.get("confidence", 0.85)),
            )

    session_traits = [
        ExtractedTrait(
            aspect=str(t["aspect"]),
            preference=str(t["preference"]),
            is_durable=bool(t.get("is_durable", True)),
        )
        for t in (session.get("active_session_traits") or [])
        if isinstance(t, dict) and t.get("aspect") and t.get("preference")
    ]

    qa_pairs: list[str] = []
    if req.feedback_type == "clarification_choice":
        if req.selected_option_id == "opt_fastest":
            session_judgments["w_distance"] = ScoreJudgment(score=0.95, confidence=0.95)
            session_judgments["w_open_now"] = ScoreJudgment(score=0.92, confidence=0.95)
            hard_raw["require_open_now"] = True
        elif req.selected_option_id == "opt_cheapest":
            session_judgments["w_price"] = ScoreJudgment(score=0.96, confidence=0.95)
        elif req.selected_option_id == "opt_installment_warranty":
            session_judgments["w_installment"] = ScoreJudgment(score=0.95, confidence=0.95)
            session_judgments["w_trust_freshness"] = ScoreJudgment(score=0.92, confidence=0.95)
            hard_raw["require_installment"] = True

        q_title_map = {
            str(q.get("id") or ""): str(q.get("title") or q.get("question") or "ویژگی انتخابی")
            for q in (session.get("clarification_questions") or [])
            if isinstance(q, dict)
        }
        for q_id, raw_ans in (req.clarification_answers or {}).items():
            ans_val = str(raw_ans or "").strip()
            if not ans_val:
                continue
            q_title = q_title_map.get(str(q_id), str(q_id))
            qa_pairs.append(f"{q_title}: {ans_val}" if str(q_id) not in ("timing", "store_priority", "payment") else ans_val)
            if str(q_id) not in ("timing", "store_priority", "payment"):
                session_traits = [t for t in session_traits if t.aspect != q_title]
                session_traits.append(ExtractedTrait(aspect=q_title, preference=ans_val, is_durable=not is_gift_session))
                cleaned_ans_parts = extract_search_tokens(ans_val)
                catalog_terms = list(dict.fromkeys([*cleaned_ans_parts, *catalog_terms]))[:8]

        if qa_pairs:
            has_custom_product_answer = any(
                str(k) not in ("timing", "store_priority", "payment") for k in (req.clarification_answers or {})
            )
            combined_clarification_text = " — ".join([p for p in (last_query, *qa_pairs) if p])
            last_query = combined_clarification_text
            try:
                clarify_eval = await evaluate_turn_with_jev(
                    combined_clarification_text,
                    session_context=session,
                    skip_llm_extraction=not has_custom_product_answer,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

            for k, new_j in clarify_eval.session_weights.items():
                old_j = session_judgments.get(k)
                if old_j is None or new_j.score >= old_j.score:
                    session_judgments[k] = new_j

            hurdle_thresh = settings.recsys_dealbreaker_noul_threshold
            if clarify_eval.dealbreakers["require_open_now"].noul >= hurdle_thresh:
                hard_raw["require_open_now"] = True
            if clarify_eval.dealbreakers["require_installment"].noul >= hurdle_thresh:
                hard_raw["require_installment"] = True
            if clarify_eval.dealbreakers["require_warranty"].noul >= hurdle_thresh:
                hard_raw["require_warranty"] = True
            if clarify_eval.require_torob_pay:
                req_torob_pay = True
                hard_raw["require_installment"] = True
            if clarify_eval.price_tier in ("budget", "flagship"):
                saved_price_tier = clarify_eval.price_tier
            if clarify_eval.product_search_query and has_custom_product_answer:
                clean_search_query = clarify_eval.product_search_query
            if clarify_eval.catalog_search_terms:
                catalog_terms = list(dict.fromkeys([*clarify_eval.catalog_search_terms, *catalog_terms]))[:8]
            if clarify_eval.extracted_traits:
                by_asp = {t.aspect: t for t in session_traits}
                for nt in clarify_eval.extracted_traits:
                    by_asp[nt.aspect] = nt
                session_traits = list(by_asp.values())[:6]
            if clarify_eval.custom_offer_criterion:
                custom_criterion = clarify_eval.custom_offer_criterion.strip()
            if clarify_eval.min_price_toman is not None:
                min_price = clarify_eval.min_price_toman
            if clarify_eval.max_price_toman is not None:
                max_price = clarify_eval.max_price_toman
            if clarify_eval.max_distance_km is not None:
                max_dist = clarify_eval.max_distance_km
            wants_used = bool(wants_used or clarify_eval.wants_used_or_stock)

            session_msgs = list(session.get("messages") or [])
            session_msgs.append({"role": "user", "text": " ؛ ".join(qa_pairs)})
            session["messages"] = session_msgs[-20:]

    profile_mutated = False
    if req.feedback_type == "weight_override" and req.weight_overrides:
        explicit_deltas = {k: float(v) for k, v in req.weight_overrides.items()}
        for k, v in explicit_deltas.items():
            session_judgments[k] = ScoreJudgment(score=float(v), confidence=0.96)
        user_profile = update_store_weights_contrastive(
            user_profile,
            explicit_deltas=explicit_deltas,
        )
        profile_mutated = True

    include_custom = bool(custom_criterion)
    active_slots, l1_weights, eff_conf = fuse_and_normalize_weights(
        user_profile,
        session_judgments,
        include_custom_offer=include_custom,
        custom_offer_label_fa=(f"شرط خاص: {custom_criterion[:24]}" if include_custom else None),
    )

    clarify_count = int(session.get("clarification_count", 0))
    is_thumbs_down = req.feedback_type == "thumbs_down"
    is_targeted_thumbs_down = bool(
        is_thumbs_down and (req.target_offer_id is not None or req.target_product_id is not None)
    )
    should_ask = False
    next_clarify_count = clarify_count
    shown_prev: dict[str, dict[str, Any]] = dict(session.get("shown_store_features") or {})

    # Policy A2:
    # - Targeted `thumbs_down` (`target_offer_id` / `target_product_id`) blacklists the item/shop and returns fresh ranked stores immediately.
    # - Message-level `thumbs_down` (no target IDs) triggers anti-fatigue clarification (`0 -> 1 -> 2`, capped at `2`).
    if is_targeted_thumbs_down:
        if req.target_offer_id is not None:
            toid = str(req.target_offer_id)
            if toid not in rej_offers:
                rej_offers.append(toid)
            prev_info = shown_prev.get(toid) or {}
            if prev_info.get("shop_id") and str(prev_info["shop_id"]) not in rej_shops:
                rej_shops.append(str(prev_info["shop_id"]))
        if req.target_offer_id is None and req.target_product_id is not None:
            tpid = str(req.target_product_id)
            if tpid not in rej_prods:
                rej_prods.append(tpid)
        should_ask = False
    elif is_thumbs_down:
        if clarify_count == 0:
            should_ask, next_clarify_count = True, 1
        else:
            should_ask, next_clarify_count = should_trigger_clarification(
                effective_confidence=eff_conf,
                clarification_count=clarify_count,
                explicit_thumbs_down=True,
                dissatisfied_noul=0.95,
            )
        if not should_ask and shown_prev:
            first_prev_oid = next(iter(shown_prev.keys()))
            if first_prev_oid not in rej_offers:
                rej_offers.append(first_prev_oid)

    dissatisfaction_triggered = bool(is_thumbs_down and should_ask)
    hard_constraints = HardConstraintsState(**hard_raw)
    lat = float(session.get("user_lat") or settings.default_user_lat)
    lng = float(session.get("user_lng") or settings.default_user_lng)

    transferred_traits = list(session.get("transferred_traits") or [])
    active_traits = _merge_active_traits(session_traits, transferred_traits)

    raw_products: list[dict[str, Any]] = []
    raw_offers: list[dict[str, Any]] = []
    product_cards: list[RecommendedProductItem] = []
    scored_stores: list[Any] = []
    unmet_labels: list[str] = []
    comp_matrix: ComparisonTableWidget | None = None
    price_span = dict(session.get("category_price_span") or {})

    if should_ask:
        active_cat = str(session.get("active_category_name") or "محصولات منتخب")
    else:
        saved_prod_dicts = [
            p for p in list(session.get("recommended_products") or [])
            if isinstance(p, dict) and str(p.get("product_id")) not in rej_prods
        ]
        need_product_rescore = (
            req.feedback_type == "clarification_choice"
            or (is_targeted_thumbs_down and req.target_offer_id is None and req.target_product_id is not None)
            or not saved_prod_dicts
        )
        if pg_pool is not None and clean_search_query:
            if need_product_rescore:
                raw_products = await search_products(
                    pg_pool,
                    query=clean_search_query,
                    min_price_toman=min_price,
                    max_price_toman=max_price,
                    price_tier=saved_price_tier,
                    category_keywords=cat_keywords,
                    is_accessory_request=is_acc_req,
                    catalog_search_terms=catalog_terms,
                    excluded_product_ids=rej_prods,
                    limit=8,
                    redis_client=redis_client,
                )
                if raw_products:
                    price_span = _extract_category_price_span(raw_products)
                    if any(bool(p.get("budget_relaxed")) for p in raw_products) and max_price:
                        unmet_labels.append(f"سقف بودجه {to_persian_digits(f'{int(max_price):,}')} تومان")
                    cumulative_fb_req = " — ".join(
                        [p for p in (last_query or clean_search_query, *qa_pairs, " ، ".join(catalog_terms[:4])) if p]
                    )
                    try:
                        raw_products = await score_candidate_products_with_decision_model(
                            user_message=cumulative_fb_req,
                            candidates=raw_products,
                            active_traits=active_traits,
                            max_price_toman=max_price,
                            min_price_toman=min_price,
                            price_tier=saved_price_tier,
                            limit=4,
                            is_accessory_request=is_acc_req,
                            wants_used_or_stock=wants_used,
                        )
                        if (
                            max_price
                            and not is_acc_req
                            and not any(
                                p.get("is_core_device", True) and (wants_used or not p.get("is_stock_or_copy", False))
                                for p in raw_products
                            )
                        ):
                            relaxed_fb = await search_products(
                                pg_pool,
                                query=clean_search_query,
                                min_price_toman=min_price,
                                max_price_toman=None,
                                price_tier="budget",
                                category_keywords=cat_keywords,
                                is_accessory_request=is_acc_req,
                                catalog_search_terms=catalog_terms,
                                excluded_product_ids=rej_prods,
                                limit=8,
                                redis_client=redis_client,
                            )
                            if relaxed_fb:
                                scored_fb = await score_candidate_products_with_decision_model(
                                    user_message=cumulative_fb_req,
                                    candidates=relaxed_fb,
                                    active_traits=active_traits,
                                    max_price_toman=None,
                                    min_price_toman=min_price,
                                    price_tier="budget",
                                    limit=4,
                                    is_accessory_request=is_acc_req,
                                    wants_used_or_stock=wants_used,
                                )
                                if any(p.get("is_core_device", True) for p in scored_fb):
                                    raw_products = scored_fb
                                    unmet_labels.append(f"سقف بودجه {to_persian_digits(f'{int(max_price):,}')} تومان")
                    except RuntimeError as exc:
                        raise HTTPException(status_code=503, detail=str(exc)) from exc
                product_cards = _build_recommended_product_cards(raw_products)
            else:
                product_cards = [
                    RecommendedProductItem(**p) for p in saved_prod_dicts if isinstance(p, dict)
                ]

            if product_cards:
                target_pids = [str(p.product_id) for p in product_cards[:3]]
                cat_name = str(product_cards[0].category_name)
                raw_offers = await fetch_candidate_offers(
                    pg_pool,
                    product_ids=target_pids,
                    user_lat=lat,
                    user_lng=lng,
                    category_name=cat_name,
                    max_price_toman=max_price,
                    redis_client=redis_client,
                    require_installment=hard_constraints.require_installment,
                    require_torob_pay=req_torob_pay,
                    require_warranty=hard_constraints.require_warranty,
                    max_distance_km=max_dist,
                    excluded_offer_ids=rej_offers,
                    excluded_shop_ids=rej_shops,
                )
                if include_custom and raw_offers and need_product_rescore:
                    try:
                        raw_offers = await score_custom_offer_criterion_with_decision_model(
                            custom_criterion,
                            raw_offers,
                        )
                    except RuntimeError as exc:
                        raise HTTPException(status_code=503, detail=str(exc)) from exc

        scored_stores, store_unmet = score_and_rank_offers_with_meta(
            raw_offers,
            l1_weights=l1_weights,
            hard_constraints=hard_constraints,
            max_distance_km=max_dist,
            require_torob_pay=req_torob_pay,
            max_price_toman=max_price,
            wants_used_or_stock=wants_used,
        )
        for ul in store_unmet:
            if ul not in unmet_labels:
                unmet_labels.append(ul)
        comp_matrix = _build_inline_comparison_matrix(product_cards)
        active_cat = (
            product_cards[0].category_name
            if product_cards
            else str(session.get("active_category_name") or "محصولات منتخب")
        )
        if product_cards:
            session["recommended_products"] = [p.model_dump() for p in product_cards]

        # Post-Session Consolidation strictly on positive `thumbs_up` / store selection (never on gift or thumbs_down)
        if req.feedback_type == "thumbs_up" and not is_gift_session:
            shown_map: dict[str, dict[str, Any]] = dict(session.get("shown_store_features") or {})
            if scored_stores:
                for s in scored_stores:
                    shown_map.setdefault(
                        str(s.offer_id),
                        {
                            "feature_scores": dict(s.feature_scores),
                            "price_toman": int(s.price_toman),
                            "product_id": str(s.product_id),
                            "shop_id": str(s.shop_id),
                        },
                    )
            if shown_map:
                target_key = (
                    str(req.target_offer_id)
                    if req.target_offer_id is not None and str(req.target_offer_id) in shown_map
                    else next(iter(shown_map.keys()))
                )
                chosen_entry = shown_map[target_key]
                shown_feat_list = [dict(v.get("feature_scores") or {}) for v in shown_map.values()]
                user_profile = update_store_weights_contrastive(
                    user_profile,
                    selected_features=dict(chosen_entry.get("feature_scores") or {}),
                    shown_features_list=shown_feat_list,
                )

                chosen_price = int(chosen_entry.get("price_toman") or 0)
                p10 = int(price_span.get("p10") or 0)
                p90 = int(price_span.get("p90") or 0)
                if chosen_price > 0 and p90 > p10:
                    obs_pct = max(0.0, min(1.0, float(chosen_price - p10) / float(p90 - p10)))
                    user_profile = update_category_price_percentile(user_profile, active_cat, obs_pct)

                profile_mutated = True
                active_slots, l1_weights, eff_conf = fuse_and_normalize_weights(
                    user_profile,
                    session_judgments,
                    include_custom_offer=include_custom,
                    custom_offer_label_fa=(f"شرط خاص: {custom_criterion[:24]}" if include_custom else None),
                )

            if session_traits:
                background_tasks.add_task(
                    sync_user_traits,
                    req.user_id,
                    active_cat,
                    session_traits,
                    pg_pool,
                    False,
                    settings.recsys_trait_confirmed_step,
                )

    clarification_card = (
        build_clarification_card(
            active_cat,
            next_clarify_count,
            custom_questions=session.get("clarification_questions"),
        )
        if should_ask
        else None
    )

    if should_ask:
        assistant_text = _compose_assistant_summary_fa(
            query=last_query,
            products=[],
            stores=[],
            clarification_triggered=True,
            dissatisfaction_triggered=dissatisfaction_triggered,
            category_name=active_cat,
        )
    elif is_targeted_thumbs_down:
        assistant_text = (
            "✅ **گزینهٔ ردشده از لیست پیشنهادها حذف شد** و بهترین فروشگاه‌های جایگزین تهران جایگزین شدند:\n\n"
            + _compose_assistant_summary_fa(
                query=last_query,
                products=product_cards,
                stores=scored_stores,
                clarification_triggered=False,
                dissatisfaction_triggered=False,
                category_name=active_cat,
                unmet_constraints_fa=unmet_labels,
            )
        )
    else:
        assistant_text = (
            "✅ **اولویت‌های شما در موتور رتبه‌بندی ترب‌چیت اعمال شد** و فروشگاه‌های حضوری تهران بر اساس وزن‌های جدید بازآرایی شدند:\n\n"
            + _compose_assistant_summary_fa(
                query=last_query,
                products=product_cards,
                stores=scored_stores,
                clarification_triggered=False,
                dissatisfaction_triggered=False,
                category_name=active_cat,
                unmet_constraints_fa=unmet_labels,
            )
        )

    session["last_query"] = last_query
    session["product_search_query"] = clean_search_query
    session["catalog_search_terms"] = catalog_terms
    session["custom_offer_criterion"] = custom_criterion
    session["wants_used_or_stock"] = wants_used
    session["max_distance_km"] = max_dist
    session["require_torob_pay"] = req_torob_pay
    session["rejected_offer_ids"] = rej_offers
    session["rejected_shop_ids"] = rej_shops
    session["rejected_product_ids"] = rej_prods
    session["active_session_traits"] = [
        {"aspect": t.aspect, "preference": t.preference, "is_durable": t.is_durable}
        for t in session_traits
    ]
    session["price_tier"] = saved_price_tier
    session["min_price_toman"] = min_price
    session["max_price_toman"] = max_price
    if price_span:
        session["category_price_span"] = price_span
    session["active_category_name"] = active_cat
    session["session_weights"] = {
        k: {"score": v.score, "confidence": v.confidence}
        for k, v in session_judgments.items()
    }
    if scored_stores:
        session["shown_store_features"] = {
            str(s.offer_id): {
                "feature_scores": dict(s.feature_scores),
                "price_toman": int(s.price_toman),
                "product_id": str(s.product_id),
                "shop_id": str(s.shop_id),
            }
            for s in scored_stores
        }
    session["effective_weights"] = l1_weights
    session["hard_constraints"] = hard_constraints.model_dump()
    session["clarification_count"] = next_clarify_count
    session["dissatisfaction_triggered"] = dissatisfaction_triggered

    # Persist user_profile ONLY when mutated by positive selection (`thumbs_up`) or `weight_override`
    if profile_mutated:
        await save_user_profile(user_profile, pg_pool=pg_pool, redis_client=redis_client)
    await save_shopping_session(session, pg_pool=pg_pool, redis_client=redis_client)

    return ChatTurnResponse(
        session_id=req.session_id,
        assistant_text=assistant_text,
        widget_type="clarification" if should_ask else "store_ranking",
        clarification_card=clarification_card,
        recsys_state=RecSysStatePayload(
            effective_confidence=max(eff_conf, 0.88 if session_judgments else eff_conf),
            clarification_count=next_clarify_count,
            dissatisfaction_triggered=dissatisfaction_triggered,
            active_weights=active_slots,
            hard_constraints=hard_constraints,
        ),
        recommended_products=product_cards,
        stores=scored_stores,
        comparison_matrix=comp_matrix,
        follow_up_chips=[]
        if should_ask
        else [
            "نمایش روی نقشه تهران",
            "فقط فروشگاه‌های دارای ترب‌پی",
            "مقایسه مشخصات فنی مدل‌ها",
        ],
    )


@app.get(f"{settings.api_v1_prefix}/products/compare", response_model=CompareProductsResponse)
async def get_products_compare(
    request: Request,
    product_ids: str = Query(..., description="Comma-separated product IDs"),
    lat: float = Query(default=settings.default_user_lat),
    lng: float = Query(default=settings.default_user_lng),
) -> CompareProductsResponse:
    """Build dynamic category-aware side-by-side comparison across 2-3 products."""
    pg_pool = getattr(request.app.state, "pg_pool", None)
    if pg_pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL connection pool is not available.")

    ids = [pid.strip() for pid in product_ids.split(",") if pid.strip()]
    if not ids:
        raise HTTPException(status_code=400, detail="At least one product_id is required.")

    raw = await fetch_product_comparison(pg_pool, ids[:4], user_lat=lat, user_lng=lng)
    models: list[ComparedModelEntry] = []
    for m in raw.get("models", []):
        closest_raw = m.get("closest_open_shop")
        closest = (
            ClosestOpenShopSummary(
                shop_id=str(closest_raw["shop_id"]),
                shop_name=str(closest_raw["shop_name"]),
                distance_km=float(closest_raw["distance_km"]),
                price_toman=int(closest_raw["price_toman"]),
                mall_badge_fa=closest_raw.get("mall_badge_fa"),
            )
            if closest_raw
            else None
        )
        models.append(
            ComparedModelEntry(
                product_id=str(m["product_id"]),
                name=str(m["name"]),
                brand_name=m.get("brand_name"),
                image_url=str(m.get("image_url") or ""),
                min_in_person_price_toman=int(m.get("min_in_person_price_toman") or 0),
                open_stores_count=int(m.get("open_stores_count") or 0),
                closest_open_shop=closest,
                specs=dict(m.get("specs") or {}),
                pros_fa=list(m.get("pros_fa") or []),
                cons_fa=list(m.get("cons_fa") or []),
            )
        )
    return CompareProductsResponse(
        category_name=str(raw.get("category_name") or "محصولات منتخب"),
        spec_keys=list(raw.get("spec_keys") or []),
        models=models,
    )


@app.get(f"{settings.api_v1_prefix}/stores/{{offer_id}}/fallback", response_model=FallbackStoreResponse)
async def get_store_fallback(
    offer_id: str,
    request: Request,
    lat: float = Query(default=settings.default_user_lat),
    lng: float = Query(default=settings.default_user_lng),
    excluded_shop_ids: str | None = Query(default=None),
) -> FallbackStoreResponse:
    """Find the best 1-tap open backup store when a shop is closed or out of stock."""
    pg_pool = getattr(request.app.state, "pg_pool", None)
    if pg_pool is None:
        raise HTTPException(status_code=503, detail="PostgreSQL connection pool is not available.")

    excluded = [s.strip() for s in (excluded_shop_ids or "").split(",") if s.strip()]
    res = await fetch_fallback_store(
        pg_pool,
        offer_id=offer_id,
        user_lat=lat,
        user_lng=lng,
        excluded_shop_ids=excluded,
    )
    if res is None:
        raise HTTPException(status_code=404, detail="No fallback store found for this offer.")

    scored = score_and_rank_offers(
        [res["alternative_store"]],
        l1_weights=l1_normalize_weights(settings.default_store_weights),
        hard_constraints=HardConstraintsState(),
        limit=1,
    )
    return FallbackStoreResponse(
        fallback_type=res["fallback_type"],
        banner_fa=res["banner_fa"],
        alternative_store=scored[0],
    )


# Mount built React SPA (`UI_Template/dist`) when present for unified Liara container serving
_DIST_DIR = Path(__file__).resolve().parent.parent / "UI_Template" / "dist"
if _DIST_DIR.is_dir():
    _ASSETS_DIR = _DIST_DIR / "assets"
    if _ASSETS_DIR.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="spa_assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="API route not found")
        candidate = _DIST_DIR / full_path
        if full_path and candidate.is_file():
            return FileResponse(str(candidate))
        index_file = _DIST_DIR / "index.html"
        if index_file.is_file():
            return FileResponse(str(index_file))
        raise HTTPException(status_code=404, detail="SPA index not found")
