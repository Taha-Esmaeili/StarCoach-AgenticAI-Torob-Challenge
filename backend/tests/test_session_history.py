"""Tests for persistent shopping conversation history (PostgreSQL + Redis + REST API)."""

import asyncpg
import pytest
from httpx import ASGITransport, AsyncClient

from backend.config import settings
from backend.db.profiles import (
    build_default_session,
    delete_user_shopping_session,
    get_user_shopping_session_detail,
    list_user_shopping_sessions,
    save_shopping_session,
)
from backend.main import app


@pytest.mark.asyncio
async def test_session_history_memory_and_pg_roundtrip():
    uid = "usr_pytest_history_check_001"
    sid_empty = "sess_pytest_empty_001"
    sid_chat = "sess_pytest_chat_001"

    pool = await asyncpg.create_pool(dsn=settings.asyncpg_dsn, min_size=1, max_size=2)
    try:
        # Clean any stale test rows first
        await delete_user_shopping_session(sid_empty, uid, pg_pool=pool)
        await delete_user_shopping_session(sid_chat, uid, pg_pool=pool)

        # 1. Empty session must NOT clutter user history list
        empty_sess = build_default_session(sid_empty, uid)
        await save_shopping_session(empty_sess, pg_pool=pool)
        listed_before = await list_user_shopping_sessions(uid, pg_pool=pool)
        assert all(item["session_id"] != sid_empty for item in listed_before)

        # 2. Non-empty session with rich UI turns persists and restores cleanly
        rich_sess = build_default_session(sid_chat, uid)
        rich_sess["title"] = "خرید حضوری هندزفری بلوتوثی در تهران"
        rich_sess["active_category_name"] = "هدفون، هدست و هندزفری"
        rich_sess["require_torob_pay"] = True
        rich_sess["hard_constraints"] = {
            "require_open_now": True,
            "require_installment": True,
            "require_warranty": False,
        }
        rich_sess["active_weight_slots"] = [
            {
                "slot": 1,
                "key": "price",
                "label_fa": "رقابت‌پذیری قیمت",
                "slot_group": "base",
                "weight": 0.4,
                "unconstrained_weight": 0.7,
                "confidence": 0.85,
            }
        ]
        rich_sess["messages"] = [{"role": "user", "text": "خرید حضوری هندزفری بلوتوثی در تهران"}]
        rich_sess["ui_turns"] = [
            {
                "id": "user-101",
                "sender": "user",
                "text": "خرید حضوری هندزفری بلوتوثی در تهران",
                "created_at": "2026-11-15T00:00:00+00:00",
            },
            {
                "id": "ai-102",
                "sender": "assistant",
                "text": "مدل‌های پیشنهادی برای شما:",
                "created_at": "2026-11-15T00:00:02+00:00",
            },
        ]
        await save_shopping_session(rich_sess, pg_pool=pool)

        listed_after = await list_user_shopping_sessions(uid, pg_pool=pool)
        matching = [item for item in listed_after if item["session_id"] == sid_chat]
        assert len(matching) == 1
        assert matching[0]["title"] == "خرید حضوری هندزفری بلوتوثی در تهران"

        # Wrong user_id must not access another user's session
        wrong_detail = await get_user_shopping_session_detail(
            sid_chat, "usr_someone_else", pg_pool=pool
        )
        assert wrong_detail is None

        # Correct user_id restores full UI turns, weights, and filter flags
        detail = await get_user_shopping_session_detail(sid_chat, uid, pg_pool=pool)
        assert detail is not None
        assert detail["require_torob_pay"] is True
        assert detail["hard_constraints"]["require_open_now"] is True
        assert len(detail["ui_turns"]) == 2
        assert detail["active_weights"][0]["key"] == "price"

        # 3. Verify HTTP REST endpoints directly via ASGI transport
        app.state.pg_pool = pool
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            list_resp = await client.get(f"/api/v1/users/{uid}/sessions")
            assert list_resp.status_code == 200
            sessions_json = list_resp.json()["sessions"]
            assert any(s["session_id"] == sid_chat for s in sessions_json)

            detail_resp = await client.get(
                f"/api/v1/sessions/{sid_chat}", params={"user_id": uid}
            )
            assert detail_resp.status_code == 200
            body = detail_resp.json()
            assert body["title"] == "خرید حضوری هندزفری بلوتوثی در تهران"
            assert len(body["ui_turns"]) == 2

            del_resp = await client.delete(
                f"/api/v1/sessions/{sid_chat}", params={"user_id": uid}
            )
            assert del_resp.status_code == 200
            assert del_resp.json()["deleted"] is True

            missing_resp = await client.get(
                f"/api/v1/sessions/{sid_chat}", params={"user_id": uid}
            )
            assert missing_resp.status_code == 404

        await delete_user_shopping_session(sid_empty, uid, pg_pool=pool)
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_location_update_recalculates_store_distances():
    uid = "usr_pytest_loc_update_001"
    sid = "sess_pytest_loc_update_001"

    pool = await asyncpg.create_pool(dsn=settings.asyncpg_dsn, min_size=1, max_size=2)
    try:
        await delete_user_shopping_session(sid, uid, pg_pool=pool)

        sample_row = await pool.fetchrow(
            """
            SELECT p.product_id, p.persian_title, p.category_name, MIN(o.price_toman)::bigint AS min_p, MAX(o.price_toman)::bigint AS max_p, COUNT(*)::int AS cnt
            FROM products p
            JOIN offers o ON o.product_id = p.product_id
            JOIN shops s ON s.shop_id = o.shop_id
            WHERE s.latitude IS NOT NULL
              AND o.price_toman > 1000000
              AND p.normalized_name NOT LIKE '%حذف شده%'
              AND p.category_name NOT LIKE '%حذف%'
            GROUP BY p.product_id, p.persian_title, p.category_name
            HAVING COUNT(*) >= 3
            LIMIT 1
            """
        )
        assert sample_row is not None

        sess = build_default_session(sid, uid, lat=35.7118, lng=51.4072)
        sess["last_query"] = sample_row["persian_title"]
        sess["product_search_query"] = sample_row["persian_title"]
        sess["active_category_name"] = sample_row["category_name"]
        sess["recommended_products"] = [
            {
                "product_id": sample_row["product_id"],
                "title": sample_row["persian_title"],
                "english_title": "",
                "category_id": 1,
                "category_name": sample_row["category_name"],
                "brand_name": None,
                "image_url": "",
                "min_price_toman": int(sample_row["min_p"]),
                "max_price_toman": int(sample_row["max_p"]),
                "store_count": int(sample_row["cnt"]),
                "match_score": 90,
                "best_for_fa": "تست موقعیت",
                "badge_fa": None,
                "pros_fa": [],
                "cons_fa": [],
                "specs": {},
            }
        ]
        sess["ui_turns"] = [
            {
                "id": "ai-1",
                "sender": "assistant",
                "text": "پیشنهادها:",
                "turn_response": {"stores": [{"offer_id": "placeholder"}]},
            }
        ]
        await save_shopping_session(sess, pg_pool=pool)

        app.state.pg_pool = pool
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            r_west = await client.post(
                "/api/v1/feedback",
                json={
                    "session_id": sid,
                    "user_id": uid,
                    "feedback_type": "location_update",
                    "user_location": {"lat": 35.7415, "lng": 51.2155},
                },
            )
            assert r_west.status_code == 200
            stores_west = r_west.json()["stores"]
            assert len(stores_west) >= 1

            r_east = await client.post(
                "/api/v1/feedback",
                json={
                    "session_id": sid,
                    "user_id": uid,
                    "feedback_type": "location_update",
                    "user_location": {"lat": 35.7362, "lng": 51.5362},
                },
            )
            assert r_east.status_code == 200
            stores_east = r_east.json()["stores"]
            assert len(stores_east) >= 1

            west_by_id = {s["offer_id"]: s["distance_km"] for s in stores_west}
            east_by_id = {s["offer_id"]: s["distance_km"] for s in stores_east}
            shared_ids = set(west_by_id.keys()) & set(east_by_id.keys())
            if shared_ids:
                oid = next(iter(shared_ids))
                assert west_by_id[oid] != east_by_id[oid]

        await delete_user_shopping_session(sid, uid, pg_pool=pool)
    finally:
        await pool.close()
