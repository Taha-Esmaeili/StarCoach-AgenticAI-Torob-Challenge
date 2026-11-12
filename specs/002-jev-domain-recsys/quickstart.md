# Phase 1 Quickstart & Validation Guide: Two-Stage Jev RecSys

**Feature**: `002-jev-domain-recsys` | **Date**: 2026-11-12 | **Spec**: [spec.md](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/specs/002-jev-domain-recsys/spec.md)

---

## 1. Prerequisites & Environment Setup

All hyperparameters and service credentials are loaded from `.env` via `backend/config.py`:

```bash
# Run unit & contract test suite using the project virtual environment
uv run pytest backend/tests/ -v
```

---

## 2. End-to-End Verification Scenarios

### Scenario 1: Domain Isolation (`electronics` vs. `footwear_apparel`) — `SC-002`
1. Send a turn for `user_1` in `electronics`:
   - Query: `"یه هندزفری بلوتوثی با باتری قوی و تاخیر کم برای گیمینگ می‌خوام"`
   - Verify background trait memory stores `domain = "electronics"` traits (`باتری و شارژدهی`, `کاربری گیمینگ و تاخیر صدا`).
2. Send a turn for `user_1` in `footwear_apparel`:
   - Query: `"یه کفش پیاده‌روی با کفی طبی می‌خوام"`
   - Verify `fetch_domain_traits_pgvector(user_id="user_1", domain="footwear_apparel")` returns **zero** `electronics` traits, and `user_1`'s `electronics` traits remain intact when switching back.

### Scenario 2: Polarity-Safe Trait Update (Antonym Resolution) — `SC-003`
1. User `user_1` has an existing trait in `electronics`:
   - `aspect = "وزن و ابعاد دستگاه"`, `preference = "سبک و قابل‌حمل"`
2. User sends a new message in `electronics` with opposite polarity on the same axis:
   - `"حالا یه لپ‌تاپ بدنه فلزی سنگین و صنعتی برای روی میز می‌خوام"`
3. Verify `sync_user_domain_traits` matches the existing `"وزن و ابعاد دستگاه"` aspect (`cosine >= 0.60` + `Jev` `Noul >= 0.70`) and **updates** `preference` in-place rather than inserting a duplicate row.

### Scenario 3: Non-Diluted Store Weight & Emergency Profile Stability — `SC-001` & `SC-005`
1. Send a single-priority query:
   - `"ارزان‌ترین فروشگاه گوشی A55 در تهران کجاست؟"`
2. Verify in `ChatTurnResponse.recsys_state.active_weights`:
   - `w_price` receives normalized weight `>= 0.80` (`> 80%` share, zero dilution from unmentioned criteria).
   - Stored `user_profiles.base_weights` in DB remains unchanged after the chat turn (`SC-005`), and only updates when `POST /api/v1/feedback` is called.
