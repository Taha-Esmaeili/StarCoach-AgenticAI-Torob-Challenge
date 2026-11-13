"""FastAPI application entrypoint for Torob Smart In-Person Shopping Assistant."""

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
from backend.db.normalizer import to_persian_digits
from backend.db.postgres import ensure_schema
from backend.db.profiles import (
    fetch_domain_traits_pgvector,
    load_shopping_session,
    load_user_profile,
    save_shopping_session,
    save_user_profile,
)
from backend.db.queries import (
    fetch_candidate_categories,
    fetch_candidate_offers,
    fetch_fallback_store,
    fetch_product_comparison,
    rerank_products_with_domain_traits,
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
from backend.recsys.deduplicator import sync_user_domain_traits
from backend.recsys.jev_engine import (
    ScoreJudgment,
    embed_text_async,
    evaluate_turn_with_jev,
    score_candidate_products_with_decision_model,
)
from backend.recsys.scorer import score_and_rank_offers
from backend.recsys.weights import (
    fuse_and_normalize_weights,
    update_profile_ema_unconstrained,
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
    version="0.2.0",
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


def _build_recommended_product_cards(
    raw_products: list[dict[str, Any]],
    domain_traits: list[dict[str, Any]] | None = None,
) -> list[RecommendedProductItem]:
    cards: list[RecommendedProductItem] = []
    traits = domain_traits or []
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
        badge = "پیشنهاد اول ترب‌چیت" if idx == 0 else ("ارزش خرید بالا" if idx == 1 else f"{to_persian_digits(match_score)}٪ تطابق")
        min_p_fmt = to_persian_digits(f"{min_p:,}")
        sc_fmt = to_persian_digits(sc)
        specs_dict: dict[str, str] = {str(k): str(v) for k, v in (p.get("specs") or {}).items()}
        spec_highlights = [f"{k}: {v}" for k, v in list(specs_dict.items())[:2]]
        matched_traits = list(p.get("matched_traits") or [])
        if not matched_traits and traits:
            matched_traits = [str(traits[0].get("preference") or "")][:1]
        trait_suffix = (
            f" • هماهنگ با سلیقه تخصصی شما ({'، '.join(t for t in matched_traits if t)})"
            if any(matched_traits)
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
                if any(matched_traits)
                else (spec_highlights[:1] if spec_highlights else ["تایید اصالت و امکان بررسی حضوری"])
            ),
        ]
        cards.append(
            RecommendedProductItem(
                product_id=str(p["product_id"]),
                title=str(p["title"]),
                english_title=str(p.get("english_title") or p["title"]),
                category_id=int(p.get("category_id") or 1),
                category_name=str(p.get("category_name") or "کالای دیجیتال"),
                brand_name=p.get("brand_name"),
                image_url=str(p.get("image_url") or ""),
                min_price_toman=min_p,
                max_price_toman=max_p,
                store_count=sc,
                match_score=match_score,
                best_for_fa=best_for,
                badge_fa=badge,
                pros_fa=pros_list,
                cons_fa=["نیازمند استعلام تلفنی موجودی رنگ پیش از حرکت"],
                specs=specs_dict,
            )
        )
    return cards


def _build_inline_comparison_matrix(cards: list[RecommendedProductItem]) -> ComparisonTableWidget | None:
    if len(cards) < 2:
        return None
    top_cards = cards[:3]
    headers = ["ویژگی / مشخصات", *[c.title[:34] for c in top_cards]]
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
    # Collect dynamic spec keys shared across top products
    seen_keys: list[str] = []
    for c in top_cards:
        for k in c.specs:
            if k not in seen_keys and len(seen_keys) < 4:
                seen_keys.append(k)
    for k in seen_keys:
        rows.append(
            {
                "feature": k,
                "values": [c.specs.get(k, "—") for c in top_cards],
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
) -> str:
    if dissatisfaction_triggered:
        return (
            "متوجه شدم پیشنهادهای قبلی دقیقاً مطابق سلیقه یا شرایط شما نبود. "
            "لطفاً در فرم زیر مشخص کنید کدام معیار (قیمت، مسافت، یا پرداخت اقساطی) برایتان اولویت بالاتری دارد تا پس از تکمیل اطلاعات، پیشنهادهای دقیق را برایتان آماده کنم:"
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
                "**اونی که بهت نزدیک‌تره و همین الان بازه**، **اونی که ارزان‌تره**، یا **خرید قسطی حضوری (ترب‌پی/اسنپ‌پی) و گارانتی** تا دقیق‌ترین پیشنهادها رو برات بیارم:"
            )
        return (
            f"برای اینکه بهترین مدل و مناسب‌ترین فروشگاه حضوری **«{cat_name}»** را در تهران دقیقاً مطابق شرایطتان پیدا کنم، "
            "لطفاً ابتدا در فرم زیر مشخص کنید کدوم مورد برایتان مهم‌تر است (نزدیک‌ترین فروشگاه باز، ارزان‌ترین قیمت، یا خرید قسطی) تا سراغ آیتم‌های دقیق‌تر برویم:"
        )
    if not products and not stores:
        return f"برای عبارت «{query}» در حال حاضر پیشنهاد حضوری مستقیمی یافت نشد. لطفاً نام دقیق‌تر مدل یا دسته‌بندی کالا را وارد کنید."

    top_prod = products[0] if products else None
    top_store = stores[0] if stores else None
    lines: list[str] = []
    if top_prod:
        lines.append(
            f"بر اساس بررسی **{to_persian_digits(len(products))} مدل برتر** در دسته **«{top_prod.category_name}»**، "
            f"بهترین گزینه فعلی **{top_prod.title}** با کف قیمت حضوری **{to_persian_digits(f'{top_prod.min_price_toman:,}')} تومان** در **{to_persian_digits(top_prod.store_count)} فروشگاه تهران** است."
        )
    if top_store:
        mall_part = (
            f" ({top_store.mall_micro_guide.note_fa})"
            if top_store.mall_micro_guide and top_store.mall_micro_guide.note_fa
            else ""
        )
        lines.append(
            f"- **بهترین فروشگاه پیشنهادی**: **{top_store.shop_name}**{mall_part} با فاصله **{to_persian_digits(top_store.distance_km)} کیلومتر** و امتیاز مطلوبیت **{to_persian_digits(top_store.utility_score)}٪**."
        )
    return "\n\n".join(lines)


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
    """Execute a full conversational shopping turn powered by Two-Stage Jev Domain RecSys."""
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

    # 1. Parallel System One Evaluation (Domain Choice, Target Category Choice, Intent Choice, 5 Store Scores, Hurdles, Domain Traits)
    cand_cats = await fetch_candidate_categories(pg_pool, req.message, limit=10)
    try:
        eval_res = await evaluate_turn_with_jev(
            req.message,
            session_context=session,
            candidate_categories=cand_cats,
        )
        query_vec = await embed_text_async(req.message)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    # 2. Fast Online Read (< 2 ms) of Domain-Scoped Traits for `(user_id, eval_res.domain)`
    domain_traits = await fetch_domain_traits_pgvector(
        pg_pool,
        user_id=req.user_id,
        domain=eval_res.domain,
        query_embedding=query_vec,
        limit=settings.recsys_max_traits_per_query,
    )

    # 3. Zero-Latency Async Background Write for newly extracted durable domain traits (`SC-004`)
    if eval_res.extracted_traits:
        background_tasks.add_task(
            sync_user_domain_traits,
            req.user_id,
            eval_res.domain,
            eval_res.extracted_traits,
            pg_pool,
        )

    # 4. Sparse Override Fusion + L1 Simplex Normalization across 5 orthogonal store criteria (`SC-001`)
    # Note (`SC-005`): Chat turns do NOT mutate `user_profile["base_weights"]` in the database;
    # long-term store weights only update via explicit / revealed feedback in `/api/v1/feedback`.
    active_slots, l1_weights, eff_conf = fuse_and_normalize_weights(
        user_profile,
        eval_res.session_weights,
    )

    # 5. Resolve Dealbreaker Hurdle Constraints (`Phi(i)`) from Jev Noul + explicit UI toggles
    hurdle_thresh = settings.recsys_dealbreaker_noul_threshold
    hard_constraints = HardConstraintsState(
        require_open_now=bool(
            req.ui_overrides.require_open_now
            or eval_res.dealbreakers["require_open_now"].noul >= hurdle_thresh
        ),
        require_installment=bool(
            req.ui_overrides.require_installment
            or req.ui_overrides.require_torob_pay
            or eval_res.dealbreakers["require_installment"].noul >= hurdle_thresh
        ),
        require_warranty=bool(
            req.ui_overrides.require_warranty
            or eval_res.dealbreakers["require_warranty"].noul >= hurdle_thresh
        ),
    )

    # 6. Anti-Fatigue Clarification Gate (Turn 1 low confidence < 0.45 / needs_clarification Noul >= 0.70, or dissatisfaction Noul >= 0.70)
    clarify_count = int(session.get("clarification_count", 0))
    should_ask, next_clarify_count = should_trigger_clarification(
        effective_confidence=eff_conf,
        clarification_count=clarify_count,
        explicit_thumbs_down=False,
        dissatisfied_noul=eval_res.user_dissatisfied.noul,
        needs_clarification_noul=eval_res.needs_clarification.noul,
    )
    dissatisfaction_triggered = bool(should_ask and clarify_count >= 1)

    # 7. If asking clarification questions, find preview candidates for the text summary and defer full recommendation cards until user answers
    min_price = eval_res.min_price_toman
    max_price = req.ui_overrides.max_price_toman or eval_res.max_price_toman
    clean_search_query = eval_res.product_search_query or req.message
    price_tier = eval_res.price_tier
    cat_keywords = eval_res.category_keywords
    is_acc_req = eval_res.is_accessory_request
    raw_products: list[dict[str, Any]] = []
    raw_offers: list[dict[str, Any]] = []
    product_cards: list[RecommendedProductItem] = []
    scored_stores: list[Any] = []
    comp_matrix: ComparisonTableWidget | None = None
    cat_probe: list[dict[str, Any]] = []

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
                limit=3,
                redis_client=redis_client,
            )
            active_cat = (
                str(cat_probe[0]["category_name"])
                if cat_probe
                else (session.get("active_category_name") or "کالای دیجیتال")
            )
        else:
            active_cat = session.get("active_category_name") or "کالای دیجیتال"
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
                limit=8,
                redis_client=redis_client,
            )
            raw_products = rerank_products_with_domain_traits(
                raw_products,
                domain_traits=domain_traits,
                query=clean_search_query,
            )
            try:
                raw_products = await score_candidate_products_with_decision_model(
                    user_message=req.message,
                    candidates=raw_products,
                    domain_traits=domain_traits,
                    max_price_toman=max_price,
                    price_tier=price_tier,
                    limit=4,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
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
            )

        product_cards = _build_recommended_product_cards(raw_products, domain_traits=domain_traits)
        scored_stores = score_and_rank_offers(
            raw_offers,
            l1_weights=l1_weights,
            hard_constraints=hard_constraints,
            dynamic_slots=user_profile.get("dynamic_slots"),
        )
        comp_matrix = _build_inline_comparison_matrix(product_cards)
        active_cat = product_cards[0].category_name if product_cards else (session.get("active_category_name") or "کالای دیجیتال")

    clarification_card = (
        build_clarification_card(active_cat, next_clarify_count) if should_ask else None
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
    )

    # 8. Persist updated session (Note: `user_profile.base_weights` is untouched by emergency chat turns per SC-005)
    session["last_query"] = req.message
    session["product_search_query"] = clean_search_query
    session["category_keywords"] = cat_keywords
    session["is_accessory_request"] = is_acc_req
    session["price_tier"] = price_tier
    session["min_price_toman"] = min_price
    session["max_price_toman"] = max_price
    session["active_domain"] = eval_res.domain
    session["active_category_name"] = active_cat
    session["selected_product_id"] = str(req.selected_product_id) if req.selected_product_id else (product_cards[0].product_id if product_cards else session.get("selected_product_id"))
    session["session_weights"] = {
        k: {"score": v.score, "confidence": v.confidence}
        for k, v in eval_res.session_weights.items()
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
async def post_feedback(req: FeedbackRequest, request: Request) -> ChatTurnResponse:
    """Process 1-tap clarification answers, thumbs up/down feedback, or live weight slider overrides."""
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

    last_query = str(session.get("last_query") or session.get("active_category_name") or "گوشی موبایل")
    clean_search_query = str(session.get("product_search_query") or last_query)
    cat_keywords: list[str] = list(session.get("category_keywords") or [])
    is_acc_req = bool(session.get("is_accessory_request") or False)
    saved_price_tier = str(session.get("price_tier") or "mid")
    saved_min_price = session.get("min_price_toman")
    min_price = int(saved_min_price) if isinstance(saved_min_price, (int, float)) and saved_min_price > 0 else None
    saved_max_price = session.get("max_price_toman")
    max_price = int(saved_max_price) if isinstance(saved_max_price, (int, float)) and saved_max_price > 0 else None
    hard_raw = dict(session.get("hard_constraints") or {})

    # Restore Turn 1's session_weights so priorities mentioned in Turn 1 are preserved alongside Turn 2 answers
    prior_turn_weights: dict[str, ScoreJudgment] = {}
    for k, raw_j in (session.get("session_weights") or {}).items():
        if isinstance(raw_j, dict):
            prior_turn_weights[k] = ScoreJudgment(
                score=float(raw_j.get("score", 0.0)),
                confidence=float(raw_j.get("confidence", 0.85)),
            )

    session_judgments: dict[str, ScoreJudgment] = dict(prior_turn_weights)
    explicit_slider_deltas: dict[str, float] = {}

    if req.feedback_type == "clarification_choice":
        option_label_map = {
            "opt_fastest": "نزدیک‌ترین مغازه باز با حداقل مسافت و زمان",
            "opt_cheapest": "کمترین قیمت ممکن و ارزان‌ترین فروشگاه در کل تهران",
            "opt_installment_warranty": "خرید قسطی حضوری (ترب‌پی/اسنپ‌پی) و گارانتی معتبر شرکتی",
        }
        parts = [last_query]
        if req.selected_option_id and req.selected_option_id in option_label_map:
            parts.append(option_label_map[req.selected_option_id])
        for ans in (req.clarification_answers or {}).values():
            if ans and str(ans).strip():
                parts.append(str(ans).strip())
        combined_clarification_text = " — ".join(parts)

        try:
            clarify_eval = await evaluate_turn_with_jev(
                combined_clarification_text,
                session_context=session,
                skip_llm_extraction=True,
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

        if clarify_eval.price_tier in ("budget", "flagship"):
            saved_price_tier = clarify_eval.price_tier
        if clarify_eval.min_price_toman:
            min_price = clarify_eval.min_price_toman
        if clarify_eval.max_price_toman:
            max_price = clarify_eval.max_price_toman

    if req.weight_overrides:
        explicit_slider_deltas.update({k: float(v) for k, v in req.weight_overrides.items()})
        for k, v in explicit_slider_deltas.items():
            session_judgments[k] = ScoreJudgment(score=float(v), confidence=0.96)

    if session_judgments or explicit_slider_deltas:
        user_profile = update_profile_ema_unconstrained(
            user_profile,
            session_judgments=session_judgments,
            explicit_deltas=explicit_slider_deltas or None,
        )

    active_slots, l1_weights, eff_conf = fuse_and_normalize_weights(user_profile, session_judgments)

    # Check if explicit `thumbs_down` triggers the Dissatisfaction-Triggered Second Chance
    clarify_count = int(session.get("clarification_count", 0))
    is_thumbs_down = req.feedback_type == "thumbs_down"
    should_ask = False
    next_clarify_count = clarify_count

    if is_thumbs_down:
        if clarify_count == 0:
            should_ask, next_clarify_count = True, 1
        else:
            should_ask, next_clarify_count = should_trigger_clarification(
                effective_confidence=eff_conf,
                clarification_count=clarify_count,
                explicit_thumbs_down=True,
                dissatisfied_noul=0.95,
            )

    dissatisfaction_triggered = bool(is_thumbs_down and should_ask)
    hard_constraints = HardConstraintsState(**hard_raw)
    active_domain = str(session.get("active_domain") or "general_retail")
    lat = float(session.get("user_lat") or settings.default_user_lat)
    lng = float(session.get("user_lng") or settings.default_user_lng)

    domain_traits = await fetch_domain_traits_pgvector(
        pg_pool,
        user_id=req.user_id,
        domain=active_domain,
        limit=settings.recsys_max_traits_per_query,
    )

    raw_products: list[dict[str, Any]] = []
    raw_offers: list[dict[str, Any]] = []
    product_cards: list[RecommendedProductItem] = []
    scored_stores: list[Any] = []
    comp_matrix: ComparisonTableWidget | None = None

    if should_ask:
        active_cat = str(session.get("active_category_name") or "کالای دیجیتال")
    else:
        if pg_pool is not None:
            raw_products = await search_products(
                pg_pool,
                query=clean_search_query,
                min_price_toman=min_price,
                max_price_toman=max_price,
                price_tier=saved_price_tier,
                category_keywords=cat_keywords,
                is_accessory_request=is_acc_req,
                limit=8,
                redis_client=redis_client,
            )
            raw_products = rerank_products_with_domain_traits(
                raw_products,
                domain_traits=domain_traits,
                query=clean_search_query,
            )
            try:
                raw_products = await score_candidate_products_with_decision_model(
                    user_message=last_query,
                    candidates=raw_products,
                    domain_traits=domain_traits,
                    max_price_toman=max_price,
                    price_tier=saved_price_tier,
                    limit=4,
                )
            except RuntimeError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc
            target_pids = [str(p["product_id"]) for p in raw_products[:3]]
            cat_name = str(raw_products[0]["category_name"]) if raw_products else session.get("active_category_name")
            raw_offers = await fetch_candidate_offers(
                pg_pool,
                product_ids=target_pids,
                user_lat=lat,
                user_lng=lng,
                category_name=cat_name,
                max_price_toman=max_price,
                redis_client=redis_client,
            )

        product_cards = _build_recommended_product_cards(raw_products, domain_traits=domain_traits)
        scored_stores = score_and_rank_offers(
            raw_offers,
            l1_weights=l1_weights,
            hard_constraints=hard_constraints,
            dynamic_slots=user_profile.get("dynamic_slots"),
        )

        # Contrastive Revealed-Preference update when user selects / thumbs-up a specific store offer (`T017`)
        if req.feedback_type == "thumbs_up" and req.target_offer_id and scored_stores:
            shown_feats = [dict(s.feature_scores) for s in scored_stores]
            sel_store = next((s for s in scored_stores if str(s.offer_id) == str(req.target_offer_id)), scored_stores[0])
            user_profile = update_store_weights_contrastive(
                user_profile,
                selected_features=dict(sel_store.feature_scores),
                shown_features_list=shown_feats,
            )
            active_slots, l1_weights, eff_conf = fuse_and_normalize_weights(user_profile, session_judgments)

        comp_matrix = _build_inline_comparison_matrix(product_cards)
        active_cat = product_cards[0].category_name if product_cards else (session.get("active_category_name") or "کالای دیجیتال")

    clarification_card = (
        build_clarification_card(active_cat, next_clarify_count) if should_ask else None
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
            )
        )

    session["effective_weights"] = l1_weights
    session["hard_constraints"] = hard_constraints.model_dump()
    session["clarification_count"] = next_clarify_count
    session["dissatisfaction_triggered"] = dissatisfaction_triggered

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
    """Build dynamic category-aware side-by-side comparison across 2-3 products (`T024`)."""
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
    """Find the best 1-tap open backup store when a shop is closed or out of stock (`T026`)."""
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
        l1_weights=settings.default_base_weights,
        hard_constraints=HardConstraintsState(),
        limit=1,
    )
    return FallbackStoreResponse(
        fallback_type=res["fallback_type"],
        banner_fa=res["banner_fa"],
        alternative_store=scored[0],
    )


# Mount built React SPA (`UI_Template/dist`) when present for unified Liara container serving (`T028`)
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
