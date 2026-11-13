"""End-to-end FastAPI integration tests for `/api/v1/*` against live PostgreSQL + pgvector + Redis."""

import uuid

from fastapi.testclient import TestClient

from backend.config import settings
from backend.main import app
from backend.recsys.jev_engine import _has_valid_api_key


def test_end_to_end_shopping_journey_and_endpoints():
    session_id = f"sess_test_{uuid.uuid4().hex[:8]}"
    user_id = f"usr_test_{uuid.uuid4().hex[:8]}"
    has_live_key = _has_valid_api_key(settings.llm_api_key) or _has_valid_api_key(settings.typesafe_api_key)

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

        # 2. Chat Turn (/api/v1/chat/turn): strictly requires live model API key (returns 503 if unconfigured)
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
        else:
            assert t1_res.status_code in (200, 503)
            if t1_res.status_code == 200:
                t1 = t1_res.json()
                weight_sum = sum(w["weight"] for w in t1["recsys_state"]["active_weights"])
                assert abs(weight_sum - 1.0) < 1e-4
                if t1["clarification_card"] is not None:
                    assert t1["widget_type"] == "clarification"
                    assert t1["recommended_products"] == []
                    assert t1["stores"] == []
                    assert t1["comparison_matrix"] is None
                    assert t1["follow_up_chips"] == []

        # 3. Feedback Endpoint (/api/v1/feedback): clarification choice -> updates weights
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

        # 4. Explicit Thumbs-Down -> triggers clarification (0 -> 1 -> 2, hard capped at 2)
        fb_down_1 = client.post(
            "/api/v1/feedback",
            json={
                "session_id": session_id,
                "user_id": user_id,
                "feedback_type": "thumbs_down",
            },
        )
        assert fb_down_1.status_code == 200
        fb_down_1_data = fb_down_1.json()
        assert fb_down_1_data["clarification_card"] is not None
        assert fb_down_1_data["recommended_products"] == []
        assert fb_down_1_data["stores"] == []
        assert fb_down_1_data["comparison_matrix"] is None
        assert fb_down_1_data["follow_up_chips"] == []

        fb_down_2 = client.post(
            "/api/v1/feedback",
            json={
                "session_id": session_id,
                "user_id": user_id,
                "feedback_type": "thumbs_down",
            },
        )
        assert fb_down_2.status_code == 200

        fb_down_3 = client.post(
            "/api/v1/feedback",
            json={
                "session_id": session_id,
                "user_id": user_id,
                "feedback_type": "thumbs_down",
            },
        )
        assert fb_down_3.status_code == 200
        assert fb_down_3.json()["clarification_card"] is None
        assert fb_down_3.json()["recsys_state"]["clarification_count"] == 2

        # 5. Product Comparison Endpoint (/api/v1/products/compare)
        pids = [str(p["product_id"]) for p in fb_choice["recommended_products"][:2]]
        comp_res = client.get(
            "/api/v1/products/compare",
            params={"product_ids": ",".join(pids), "lat": 35.7219, "lng": 51.3347},
        )
        assert comp_res.status_code == 200
        comp_data = comp_res.json()
        assert len(comp_data["models"]) >= 1

        # 6. Store 1-Tap Rescue Fallback Endpoint (/api/v1/stores/{offer_id}/fallback)
        first_offer_id = fb_choice["stores"][0]["offer_id"]
        fb_store_res = client.get(
            f"/api/v1/stores/{first_offer_id}/fallback",
            params={"lat": 35.7219, "lng": 51.3347},
        )
        assert fb_store_res.status_code == 200
        fb_store = fb_store_res.json()
        assert fb_store["alternative_store"]["shop_id"] != fb_choice["stores"][0]["shop_id"]
        assert fb_store["banner_fa"]
