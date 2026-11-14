"""Phase 1 & Spec 003 contract checks: .env-driven configuration, 5+1 slot bounds, FeedbackRequest DTO, and /api/v1/health."""

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.config import Settings, settings
from backend.main import app
from backend.models.schemas import (
    ActiveWeightSlot,
    ChatTurnRequest,
    ChatTurnResponse,
    FeedbackRequest,
    RecSysStatePayload,
)


def test_settings_env_driven_entities_and_jev_mode():
    cfg_fallback = Settings(
        database_url="postgresql+asyncpg://torob:torob_secret@localhost:5432/torob_db",
        typesafe_api_key="",
        llm_base_url="https://custom.llm.local/v1",
        llm_api_key="sk-test-llm",
        recsys_clarify_confidence_threshold=0.52,
        recsys_trait_transfer_noul_threshold=0.74,
        recsys_hurdle_penalty_multiplier=0.12,
        redis_session_ttl_seconds=7200,
    )
    assert cfg_fallback.asyncpg_dsn == "postgresql://torob:torob_secret@localhost:5432/torob_db"
    assert cfg_fallback.jev_engine_mode == "openai_compatible_system_one"
    assert cfg_fallback.effective_embedding_base_url == "https://custom.llm.local/v1"
    assert cfg_fallback.effective_embedding_api_key == "sk-test-llm"
    assert cfg_fallback.recsys_total_slots == 6
    assert cfg_fallback.recsys_clarify_confidence_threshold == 0.52
    assert cfg_fallback.recsys_trait_transfer_noul_threshold == 0.74
    assert cfg_fallback.recsys_hurdle_penalty_multiplier == 0.12
    assert cfg_fallback.redis_session_ttl_seconds == 7200
    assert len(cfg_fallback.default_store_weights) == 5
    assert cfg_fallback.recsys_max_preferences_per_aspect == 2
    assert cfg_fallback.recsys_custom_offer_top_k == 15

    # Ensure legacy 15-slot attributes were completely purged
    assert not hasattr(cfg_fallback, "default_base_weights")
    assert not hasattr(cfg_fallback, "default_persona_weights")
    assert not hasattr(cfg_fallback, "recsys_dynamic_slots")

    cfg_typesafe = Settings(
        typesafe_api_key="ts_live_123",
        embedding_base_url="https://embed.custom.local/v1",
        embedding_api_key="sk-embed-only",
        cors_allow_origins="http://localhost:3000, https://torob.liara.run",
    )
    assert cfg_typesafe.jev_engine_mode == "typesafe_sdk"
    assert cfg_typesafe.effective_embedding_base_url == "https://embed.custom.local/v1"
    assert cfg_typesafe.effective_embedding_api_key == "sk-embed-only"
    assert cfg_typesafe.cors_origins_list == ["http://localhost:3000", "https://torob.liara.run"]


def test_pydantic_contracts_validation():
    req = ChatTurnRequest(
        session_id="sess_01",
        message="یه هندزفری بلوتوثی تا ۲ میلیون سمت ولیعصر میخوام",
    )
    assert req.user_id == settings.default_user_id
    assert req.user_location.lat == settings.default_user_lat
    assert req.user_location.lng == settings.default_user_lng
    assert req.ui_overrides.require_open_now is False

    resp = ChatTurnResponse(
        session_id="sess_01",
        assistant_text="۳ فروشگاه پیدا شد",
        widget_type="store_ranking",
        recsys_state=RecSysStatePayload(
            effective_confidence=0.84,
            clarification_count=0,
            active_weights=[
                ActiveWeightSlot(
                    slot=1,
                    key="w_price",
                    label_fa="کمترین قیمت",
                    slot_group="base",
                    weight=0.5,
                    unconstrained_weight=0.8,
                    confidence=0.9,
                ),
                ActiveWeightSlot(
                    slot=6,
                    key="w_offer_custom",
                    label_fa="تطابق شرط خاص فروشگاهی",
                    slot_group="dynamic",
                    weight=0.5,
                    unconstrained_weight=0.75,
                    confidence=0.88,
                ),
            ],
        ),
    )
    assert resp.recsys_state.active_weights[1].slot == 6

    with pytest.raises(ValidationError):
        ActiveWeightSlot(
            slot=7,
            key="w_invalid",
            label_fa="نامعتبر",
            slot_group="dynamic",
            weight=0.1,
            unconstrained_weight=0.1,
            confidence=0.5,
        )

    fb = FeedbackRequest(
        session_id="sess_01",
        feedback_type="thumbs_up",
        target_offer_id="offer_123",
        target_product_id="prod_456",
    )
    assert fb.user_id == settings.default_user_id
    assert fb.feedback_type == "thumbs_up"
    assert fb.target_offer_id == "offer_123"
    assert fb.target_product_id == "prod_456"


def test_health_endpoint_contract():
    with TestClient(app) as client:
        response = client.get(f"{settings.api_v1_prefix}/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in ("ok", "degraded")
        assert "postgres_pgvector_ready" in body
        assert "redis_ready" in body
        assert "counts" in body
        assert set(body["counts"].keys()) == {"shops", "products", "offers", "real_torob_shops"}
        assert body["jev_engine_mode"] in ("typesafe_sdk", "openai_compatible_system_one")
