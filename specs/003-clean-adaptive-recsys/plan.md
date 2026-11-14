# Implementation Plan: Clean Two-Layer Adaptive Recommender System (`003-clean-adaptive-recsys`)

**Branch**: `feature/003-clean-adaptive-recsys` | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md) | **Audit Ledger**: [cleanup-and-implementation-audit.md](cleanup-and-implementation-audit.md)

**Input**: Feature specification from `specs/003-clean-adaptive-recsys/spec.md` and full codebase purge/bug-fix audit from `specs/003-clean-adaptive-recsys/cleanup-and-implementation-audit.md`.

## Summary

Deliver a **zero-bloat, zero-keyword-crutch, scientifically sound Two-Layer Adaptive `Jev` Recommender System** by executing three coordinated tracks in place across `backend/` and `UI_Template/`:
1. **Complete Legacy & Regex Purge**: Delete all dead 15-slot tables (`user_dynamic_slots`), unpopulated columns (`products.embedding`), dead functions (`upsert_dynamic_spec_slots`, `compute_fusion_alpha`, `map_clarification_answers_to_deltas`, `find_closest_dynamic_slot_pgvector`), hardcoded stopword/category regexes (`_PARTICLES_FA`, `_ACCESSORY_CATEGORY_REGEX`, substring `rerank_products_with_domain_traits`), unused `.env` settings, and the wasted online `embed_text_async` call in `post_chat_turn`.
2. **Fix All 10 Production Bugs**: Fix `HTTP 500 AttributeError` on `thumbs_up` (`target_offer_id`), eliminate hallucinated `"منطبق با سلیقه شما"` badges, stop `thumbs_down` from corrupting permanent store profiles, remove hardcoded `0.18` / `0.65` overrides masking `.env`, surface `offers.seller_title` & `offers.description` for `استوک`/seller conditions, replace destructive single-row trait overwrites with Top-2 inertia, persist full `session_context_json` in PostgreSQL (`"general"` default), physically place Pareto roles in ranks `[1, 2, 3]`, normalize fallback weights, and switch store open-hours check to `ZoneInfo("Asia/Tehran")`.
3. **Zero-Keyword Two-Layer Intelligence & Safe Consolidation**:
   - **Layer 1 (Product Selection)**: Dynamic Concept-to-Catalog Expansion (`catalog_search_terms`), parallel `Jev` `Noul` selective cross-category trait transfer (`Laptop -> Phone` using `source_category` with `0` extra network RTT), 100% Decision-Model semantic trait attribution (`6000mAh` -> `شارژدهی بالا`), and dimensionless `Domain Price Prior` ($\pi_{u,d} \in [0, 1]$).
   - **Layer 2 (Store Ranking)**: 5 orthogonal numerical metrics (`w_price`, `w_distance`, `w_open_now`, `w_trust_freshness`, `w_installment`) + conditional open-vocabulary criterion (`w_offer_custom` batched across top 15 candidate offers when user specifies target mall/neighborhood, part-number, color, or test guarantee).
   - **Post-Session Consolidation**: `is_ephemeral_or_gift` outlier shield, Top-2 per-aspect `strength` retention, and contrastive store weight updates strictly on positive UI selections.

## Technical Context

**Language/Version**: Python 3.11+ (`backend/`), TypeScript 5 / React 19 (`UI_Template/`)

**Primary Dependencies**: FastAPI, `asyncpg`, `redis.asyncio`, `httpx` (Google AI Studio Decision API `gemini-decision-1` / TypeSafe System-One `Jev` + OpenAI-compatible LLM & Embeddings), `pydantic` v2, `pydantic-settings`, `zoneinfo` (`Asia/Tehran`)

**Storage**: PostgreSQL 16 (`JSONB` + `pg_trgm` + `pgvector` for background `user_trait_memory.aspect_embedding`) + Redis 7 read/write-through session & profile cache

**Testing**: `pytest` + `pytest-asyncio` (`backend/tests/test_recsys_math.py`, `backend/tests/test_api_endpoints.py`, `backend/tests/test_phase1_contracts.py`, `backend/tests/test_ingest_guard.py`) + Vite TypeScript production build (`npm run build`)

**Target Platform**: Linux Docker container (local Docker Compose & Liara deployment)

**Project Type**: Full-stack AI shopping assistant (`backend/` FastAPI service + `UI_Template/` React RTL SPA)

**Performance Goals**: Remove ~`300 ms` wasted online embedding RTT from every chat turn; `< 20 ms` hybrid SQL retrieval over 225,903 products & 331,506 offers; `0` extra sequential Decision Model hops on standard turns (`1` parallel turn-eval call + `1` parallel product-scoring call, plus `1` conditional 15-offer call only when `custom_offer_criterion != ""`)

**Constraints**: 100% `.env`-driven thresholds (`backend/config.py` with zero hardcoded overrides), zero hardcoded domain/feature keyword dictionaries or regexes, strict `offers.csv` vs. `shops.category_names` separation, backward-compatible `UI_Template` UI widgets

**Scale/Scope**: 6,476 Tehran shops (112 verified), 225,903 products, 331,506 offers; 12 modified files across `backend/`, `UI_Template/`, and `.env.example`, with net code reduction via dead-code removal

## Constitution Check

*GATE: Passed before Phase 0 research and re-verified after Phase 1 design (`research.md`, `data-model.md`, `contracts/recsys-api.md`, `quickstart.md`).*

- **Principle 1 (300-Point Rubric & Beyond-Chat RTL UX)**: **PASS** — Preserves every `UI_Template` RTL widget, fixes true Pareto Top-3 store card ordering (`#1 Best Overall`, `#2 Closest Open`, `#3 Lowest Price`), eliminates false trait badges on product cards, and wires positive store selection (`StoreContactModal` / `ShoppingCompanionModal` / `👍`) cleanly to `/api/v1/feedback`.
- **Principle 2 (System-One Decision Model & Adaptive RecSys)**: **PASS (Evolved cleanly from `002`)** — Follows `typesafe-ai` strictly ("Judgments in `Jev`, Decisions in Code", parallel `Choice` / `Score` / `Noul`, 2-round Anti-Fatigue Clarification, unconstrained stored weights + query-time L1 normalization) while finalizing the user-approved Clean Two-Layer Architecture (`Selective Cross-Item Trait Memory + 5 Numerical & 1 Conditional Open-Vocabulary Store Criteria`).
- **Principle 3 (Torob Dataset Integrity & Transparency Guard)**: **PASS** — Preserves strict `offers.csv` join enforcement, enriches `offers` inspection with `seller_title` & `description` (`"null"`-normalized), and fixes `weekly_hours_json` open-now evaluation to `Asia/Tehran` local time.
- **Principle 4 (Ponytail Simplicity & Verification Discipline)**: **PASS** — Achieves a **smaller, cleaner codebase** by deleting ~350+ lines of dead 15-slot & regex code, using idempotent in-place SQL migrations, and backing every new/fixed behavior with deterministic `pytest` assertions.
- **Principle 5 (Dual-Base Git Workflow & 3-Gate Approvals)**: **PASS** — Isolated on `feature/003-clean-adaptive-recsys` branched from clean `develop`; all commits, pushes, and PRs strictly gated by 3-Gate user approval.

## Project Structure

### Documentation (this feature)

```text
specs/003-clean-adaptive-recsys/
├── spec.md                              # Feature specification (FR-001..FR-016, SC-001..SC-007)
├── cleanup-and-implementation-audit.md  # Exact file/line Purge Ledger, Bug-Fix Ledger & Target Spec
├── plan.md                              # This implementation plan
├── research.md                          # Phase 0 architectural decisions (R1..R8)
├── data-model.md                        # Phase 1 PostgreSQL + Redis target schema & state rules
├── quickstart.md                        # Phase 1 end-to-end validation scenarios
├── contracts/
│   └── recsys-api.md                    # Phase 1 System-One Jev, FastAPI & UI client contracts
└── checklists/
    └── requirements.md                  # Spec quality checklist (16/16 passed)
```

### Source Code (repository root)

```text
.env.example                             # Clean two-layer RecSys settings (16 dead vars removed, new thresholds added)

backend/
├── config.py                            # 100% .env-driven Settings (dead 15-slot properties purged)
├── main.py                              # FastAPI routes (/chat/turn without online embed RTT, fixed /feedback & fallback)
├── models/
│   └── schemas.py                       # FeedbackRequest target_offer_id/target_product_id + 6-slot max ActiveWeightSlot
├── db/
│   ├── postgres.py                      # Idempotent DDL (drop user_dynamic_slots & products.embedding; upgrade 3 tables)
│   ├── normalizer.py                    # ZoneInfo("Asia/Tehran") fix in evaluate_weekly_hours
│   ├── profiles.py                      # Clean store_weights_json, price_percentiles_json, Top-2 user_trait_memory & full session_context_json
│   └── queries.py                       # Zero-regex search_products with catalog_search_terms & offer seller_title/description boost
├── recsys/
│   ├── jev_engine.py                    # Parallel Turn-1 Jev (transfer + gift + w_offer_custom), semantic product trait attribution, 15-offer custom scorer
│   ├── deduplicator.py                  # Dead 15-slot code purged; non-destructive Top-2 per-aspect trait consolidation with gift guard
│   ├── weights.py                       # Pure .env thresholds, 5+1 Sparse Override fusion, contrastive feedback & domain price percentile math
│   ├── scorer.py                        # Dead dynamic_slots purged; custom offer score integration + physical Pareto Top-3 reordering
│   └── clarifier.py                     # Dead keyword mapper purged; legacy slot key fixed to w_trust_freshness
└── tests/
    ├── test_ingest_guard.py             # Updated schema & Asia/Tehran hours assertions
    ├── test_phase1_contracts.py         # Updated FeedbackRequest & 6-slot contract assertions
    ├── test_recsys_math.py              # Selective transfer, Top-2 inertia, gift guard, price percentile, Pareto [0,1,2] & contrastive tests
    └── test_api_endpoints.py            # End-to-end /chat/turn & /feedback (thumbs_up/thumbs_down/store select) tests

UI_Template/
└── src/
    ├── api/client.ts                    # Add optional target_offer_id & target_product_id to postFeedback
    └── App.tsx                          # Send revealed-preference feedback signal on positive store selection / companion launch
```

**Structure Decision**: In-place refinement and dead-code purge across the existing `backend/` and `UI_Template/` web application structure—zero new directories, zero speculative abstractions, and net reduction in code surface area.

## Complexity Tracking

| Evolution vs. Earlier Specs (`001` / `002`) | Why Needed | Simpler / Previous Approach Replaced Because |
|---------------------------------------------|------------|----------------------------------------------|
| Selective `Noul` Trait Transfer with `source_category` inside Turn-1 parallel `Jev` call | Enables safe cross-item history reuse (`Laptop -> Phone`, `Shoe -> Sneaker`) with `0` extra network hops | Loading all domain traits blindly leaks incompatible dimensions (`15.6"` screen into phone search); category matrices require hardcoded rules |
| Conditional 6th Store Slot `w_offer_custom` (top 15 offers only when `custom_offer_criterion != ""`) | Handles target malls/neighborhoods (`سمت چارسو`) and seller-text conditions (`پارت‌نامبر ZAA`, `مهلت تست`, `استوک`) semantically | Pure 5-number store vector is blind to unstructured address/offer text; scoring all 50 offers unconditionally would waste tokens |
| Top-2 Per-Aspect Trait Inertia + `Domain Price Prior` + Gift Shield | Prevents a single gift/outlier query or `👎` click from erasing established user taste and allows multi-brand affinity | Single-row SQL `UPDATE` in `002` wiped out `hit_count=8` preferences on a single experiment |
