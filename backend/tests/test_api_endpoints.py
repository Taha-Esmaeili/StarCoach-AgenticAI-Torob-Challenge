"""End-to-end FastAPI integration tests for `/api/v1/*` against live PostgreSQL + pgvector + Redis."""

import uuid

from fastapi.testclient import TestClient

from backend.main import app


def test_end_to_end_shopping_journey_and_endpoints():
    session_id = f"sess_test_{uuid.uuid4().hex[:8]}"
    user_id = f"usr_test_{uuid.uuid4().hex[:8]}"

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

        # 2. Turn 1: Vague query -> triggers initial clarification (clarification_count: 0 -> 1)
        t1_res = client.post(
            "/api/v1/chat/turn",
            json={
                "session_id": session_id,
                "user_id": user_id,
                "message": "یه گوشی موبایل سامسونگ میخوام",
                "user_location": {"lat": 35.7219, "lng": 51.3347},
            },
        )
        assert t1_res.status_code == 200
        t1 = t1_res.json()
        assert t1["widget_type"] == "clarification"
        assert t1["clarification_card"] is not None
        assert t1["recsys_state"]["clarification_count"] == 1
        weight_sum = sum(w["weight"] for w in t1["recsys_state"]["active_weights"])
        assert abs(weight_sum - 1.0) < 1e-4
        assert len(t1["recommended_products"]) >= 1
        assert len(t1["stores"]) >= 1

        # 3. Turn 2: Submit clarification choice via /api/v1/feedback -> updates weights, no re-ask
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
        assert fb_choice["recsys_state"]["clarification_count"] == 1
        assert fb_choice["recsys_state"]["hard_constraints"]["require_open_now"] is True

        # 4. Turn 3: Explicit Thumbs-Down -> triggers Dissatisfaction Second Chance (1 -> 2)
        fb_down_res = client.post(
            "/api/v1/feedback",
            json={
                "session_id": session_id,
                "user_id": user_id,
                "feedback_type": "thumbs_down",
            },
        )
        assert fb_down_res.status_code == 200
        fb_down = fb_down_res.json()
        assert fb_down["recsys_state"]["clarification_count"] == 2
        assert fb_down["recsys_state"]["dissatisfaction_triggered"] is True
        assert fb_down["clarification_card"] is not None
        assert fb_down["clarification_card"]["clarification_round"] == 2

        # 5. Turn 4: Another Thumbs-Down -> strictly capped at 2 (never asks a 3rd time)
        fb_down_again = client.post(
            "/api/v1/feedback",
            json={
                "session_id": session_id,
                "user_id": user_id,
                "feedback_type": "thumbs_down",
            },
        )
        assert fb_down_again.status_code == 200
        assert fb_down_again.json()["clarification_card"] is None
        assert fb_down_again.json()["recsys_state"]["clarification_count"] == 2

        # 6. Product Comparison Endpoint (/api/v1/products/compare)
        pids = [str(p["product_id"]) for p in t1["recommended_products"][:2]]
        comp_res = client.get(
            "/api/v1/products/compare",
            params={"product_ids": ",".join(pids), "lat": 35.7219, "lng": 51.3347},
        )
        assert comp_res.status_code == 200
        comp_data = comp_res.json()
        assert len(comp_data["models"]) >= 1

        # 7. Store 1-Tap Rescue Fallback Endpoint (/api/v1/stores/{offer_id}/fallback)
        first_offer_id = t1["stores"][0]["offer_id"]
        fb_store_res = client.get(
            f"/api/v1/stores/{first_offer_id}/fallback",
            params={"lat": 35.7219, "lng": 51.3347},
        )
        assert fb_store_res.status_code == 200
        fb_store = fb_store_res.json()
        assert fb_store["alternative_store"]["shop_id"] != t1["stores"][0]["shop_id"]
        assert fb_store["banner_fa"]
