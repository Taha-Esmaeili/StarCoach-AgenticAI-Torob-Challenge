"""End-to-end FastAPI integration tests for `/api/v1/*` against live PostgreSQL + pgvector + Redis:
- Verifies dataset counts, chat turn, clarification choice, 3x thumbs-down anti-fatigue cap,
  0% profile mutation on `thumbs_down` / `clarification_choice`, positive `thumbs_up` (`target_offer_id`)
  consolidation, Redis-eviction session durability (`session_context_json`), and random non-digital categories.
"""

import asyncio
import uuid

from fastapi.testclient import TestClient

from backend.config import settings
from backend.db.postgres import create_pg_pool
from backend.db.profiles import _MEMORY_SESSIONS, load_shopping_session, load_user_profile
from backend.db.queries import search_products
from backend.db.redis_cache import create_redis_client, session_key
from backend.main import app
from backend.recsys.jev_engine import _has_valid_api_key


def test_end_to_end_shopping_journey_consolidation_and_session_durability():
    session_id = f"sess_test_{uuid.uuid4().hex[:8]}"
    user_id = f"usr_test_{uuid.uuid4().hex[:8]}"
    has_live_key = _has_valid_api_key(settings.llm_api_key) and _has_valid_api_key(settings.typesafe_api_key)

    with TestClient(app) as client:
        # 1. Health & Dataset Integrity Probe
        health_res = client.get("/api/v1/health")
        assert health_res.status_code == 200
        h_data = health_res.json()
        assert h_data["status"] == "ok"
        assert h_data["postgres_pgvector_ready"] is True
        assert h_data["redis_ready"] is True
        assert h_data["counts"]["shops"] == 6476
        assert h_data["counts"]["products"] == 225903
        assert h_data["counts"]["offers"] == 331506
        assert h_data["counts"]["real_torob_shops"] == 112

        # 2. Chat Turn (/api/v1/chat/turn)
        t1_res = client.post(
            "/api/v1/chat/turn",
            json={
                "session_id": session_id,
                "user_id": user_id,
                "message": "یه گوشی موبایل سامسونگ میخوام",
                "user_location": {"lat": 35.7219, "lng": 51.3347},
            },
        )
        if not has_live_key:
            assert t1_res.status_code == 503
            return

        assert t1_res.status_code == 200, f"Unexpected status {t1_res.status_code}: {t1_res.text}"

        t1 = t1_res.json()
        weight_sum = sum(w["weight"] for w in t1["recsys_state"]["active_weights"])
        assert abs(weight_sum - 1.0) < 1e-4

        assert client.portal is not None

        # Snapshot initial persistent user profile BEFORE clarification & thumbs_down
        prof_before = client.portal.call(
            load_user_profile, user_id, app.state.pg_pool, app.state.redis
        )

        # 3. Clarification Choice -> updates session ranking ONLY, MUST NOT mutate persistent user_profile
        fb_choice_res = client.post(
            "/api/v1/feedback",
            json={
                "session_id": session_id,
                "user_id": user_id,
                "feedback_type": "clarification_choice",
                "selected_option_id": "opt_fastest",
                "clarification_answers": {"timing": "همین الان (نزدیک‌ترین مغازه باز)"},
            },
        )
        assert fb_choice_res.status_code == 200
        fb_choice = fb_choice_res.json()
        assert fb_choice["clarification_card"] is None
        assert fb_choice["recsys_state"]["hard_constraints"]["require_open_now"] is True
        assert len(fb_choice["recommended_products"]) >= 1
        assert len(fb_choice["stores"]) >= 1
        assert fb_choice["stores"][0]["pareto_role"] == "best_overall"
        initial_category = fb_choice["recommended_products"][0]["category_name"]

        # 3b. Multi-turn Store/Payment Follow-Up ("فقط فروشگاه‌های دارای ترب‌پی") MUST preserve product & category context!
        t2_followup_res = client.post(
            "/api/v1/chat/turn",
            json={
                "session_id": session_id,
                "user_id": user_id,
                "message": "فقط فروشگاه‌های دارای ترب‌پی",
                "user_location": {"lat": 35.7219, "lng": 51.3347},
            },
        )
        assert t2_followup_res.status_code == 200
        t2_followup = t2_followup_res.json()
        assert len(t2_followup["recommended_products"]) >= 1
        assert t2_followup["recommended_products"][0]["category_name"] == initial_category
        assert t2_followup["recsys_state"]["hard_constraints"]["require_installment"] is True
        assert t2_followup["recsys_state"]["hard_constraints"]["require_open_now"] is True

        # 4. Explicit Thumbs-Down (0 -> 1 -> 2, hard capped at 2) MUST NOT mutate persistent user_profile
        fb_down_1 = client.post(
            "/api/v1/feedback",
            json={"session_id": session_id, "user_id": user_id, "feedback_type": "thumbs_down"},
        )
        assert fb_down_1.status_code == 200
        assert fb_down_1.json()["clarification_card"] is not None
        assert fb_down_1.json()["stores"] == []

        fb_down_2 = client.post(
            "/api/v1/feedback",
            json={"session_id": session_id, "user_id": user_id, "feedback_type": "thumbs_down"},
        )
        assert fb_down_2.status_code == 200

        fb_down_3 = client.post(
            "/api/v1/feedback",
            json={"session_id": session_id, "user_id": user_id, "feedback_type": "thumbs_down"},
        )
        assert fb_down_3.status_code == 200
        assert fb_down_3.json()["clarification_card"] is None
        assert fb_down_3.json()["recsys_state"]["clarification_count"] == 2

        prof_after_neg = client.portal.call(
            load_user_profile, user_id, app.state.pg_pool, app.state.redis
        )
        assert prof_after_neg["store_weights"] == prof_before["store_weights"]
        assert prof_after_neg["interaction_count"] == prof_before["interaction_count"] == 0

        # 5. Positive Revealed-Preference Selection (`thumbs_up` with `target_offer_id`) -> updates user_profile!
        first_offer_id = fb_choice["stores"][0]["offer_id"]
        first_product_id = fb_choice["stores"][0]["product_id"]
        fb_up_res = client.post(
            "/api/v1/feedback",
            json={
                "session_id": session_id,
                "user_id": user_id,
                "feedback_type": "thumbs_up",
                "target_offer_id": first_offer_id,
                "target_product_id": first_product_id,
            },
        )
        assert fb_up_res.status_code == 200
        prof_after_pos = client.portal.call(
            load_user_profile, user_id, app.state.pg_pool, app.state.redis
        )
        assert prof_after_pos["interaction_count"] == 1

        # 6. Product Comparison & 1-Tap Rescue Fallback Endpoints
        pids = [str(p["product_id"]) for p in fb_choice["recommended_products"][:2]]
        comp_res = client.get(
            "/api/v1/products/compare",
            params={"product_ids": ",".join(pids), "lat": 35.7219, "lng": 51.3347},
        )
        assert comp_res.status_code == 200
        assert len(comp_res.json()["models"]) >= 1

        fb_store_res = client.get(
            f"/api/v1/stores/{first_offer_id}/fallback",
            params={"lat": 35.7219, "lng": 51.3347},
        )
        assert fb_store_res.status_code == 200
        fb_store = fb_store_res.json()
        assert fb_store["alternative_store"]["shop_id"] != fb_choice["stores"][0]["shop_id"]
        assert fb_store["banner_fa"]

        # 7. Redis Eviction Session Durability Check (`session_context_json` round-trip in PostgreSQL)
        async def _verify_pg_session_recovery():
            await app.state.redis.delete(session_key(session_id))
            _MEMORY_SESSIONS.pop(session_id, None)
            recovered = await load_shopping_session(
                session_id,
                user_id=user_id,
                pg_pool=app.state.pg_pool,
                redis_client=app.state.redis,
            )
            assert recovered["product_search_query"]
            assert recovered["clarification_count"] == 2
            assert len(recovered["shown_store_features"]) >= 1

        client.portal.call(_verify_pg_session_recovery)


def test_random_non_digital_categories_search_without_hardcoding():
    """Verify general category resolution & catalog_search_terms across diverse random Torob categories."""
    async def _run_checks():
        pool = await create_pg_pool()
        redis_client = await create_redis_client()
        try:
            for query, terms in [
                ("کفش پیاده روی", ["طبی", "سبک"]),
                ("قهوه ساز", ["اسپرسو"]),
                ("دریل", ["شارژی"]),
            ]:
                items = await search_products(
                    pool,
                    query=query,
                    catalog_search_terms=terms,
                    limit=4,
                    redis_client=redis_client,
                )
                assert len(items) >= 1
                assert items[0]["category_name"] != "کالای دیجیتال"
        finally:
            await redis_client.aclose()
            await pool.close()

    asyncio.run(_run_checks())
