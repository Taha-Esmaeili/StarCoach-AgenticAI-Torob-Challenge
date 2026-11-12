# Implementation Plan: Two-Stage Jev Recommender System with Domain-Scoped User Trait Memory

**Branch**: `feature/002-jev-domain-recsys` | **Date**: 2026-11-12 | **Spec**: [spec.md](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/specs/002-jev-domain-recsys/spec.md)

**Input**: Feature specification from `/specs/002-jev-domain-recsys/spec.md` and approved architecture in `simplified_jev_recsys_algorithm.md`.

## Summary

Refactor the recommender engine in `backend/` from the over-engineered 15-slot flat linear model into a **production-grade, scientifically defensible Two-Stage Jev Architecture**:
1. **Stage 1 (Product Selection with Domain-Scoped Trait Memory)**: Store open-vocabulary user traits partitioned by `(user_id, domain, aspect, preference)` in PostgreSQL + `pgvector` (`user_trait_memory`). Embed **only `aspect`** for fast `< 2 ms` online retrieval and run trait extraction/deduplication (`pgvector` candidate filter + `Jev` `Noul` same-aspect check) asynchronously in `FastAPI BackgroundTasks` (`0 ms` added chat latency, zero antonym collisions, 100% domain isolation between Digital Goods and Footwear/Apparel).
2. **Stage 2 (Physical Store Ranking with 5 Orthogonal Criteria)**: Score stocked store offers from `offers.csv` across 5 independent criteria (`w_price`, `w_distance`, `w_open_now`, `w_trust_freshness`, `w_installment`) using a 3-level `Jev` `Score` rubric (`0: Not Mentioned`, `1: Mild`, `2: Primary`), sparse override weighting (preventing weight dilution so a single explicit criterion gets `>= 80%` weight), outlier-resistant relative exponential price decay, dealbreaker hurdle multipliers, and revealed-preference UI feedback updates.

## Technical Context

**Language/Version**: Python 3.11+ (Backend), TypeScript / React 19 (Frontend `UI_Template/` unchanged)

**Primary Dependencies**: FastAPI, `asyncpg`, `redis.asyncio`, `httpx` (`TypeSafe` `/v1/systemone` + OpenAI-compatible `/embeddings` & `/chat/completions` fallback), `numpy`, `pydantic-settings`

**Storage**: PostgreSQL + `pgvector` + `pg_trgm` (`products`, `shops`, `offers`, `user_profiles`, `user_trait_memory`, `shopping_sessions`) and Redis read/write-through cache

**Testing**: `pytest` + `pytest-asyncio` (`backend/tests/test_recsys_math.py`, `backend/tests/test_api_endpoints.py`, `backend/tests/test_phase1_contracts.py`, `backend/tests/test_ingest_guard.py`)

**Target Platform**: Linux container (Docker / Liara deployment)

**Project Type**: Full-stack AI web application (`backend/` FastAPI service + `UI_Template/` React SPA)

**Performance Goals**: `< 600 ms` p95 end-to-end chat turn latency; `< 2 ms` online user trait vector read; `0 ms` user-facing write overhead via `FastAPI BackgroundTasks`

**Constraints**: 100% `.env`-driven configuration (`backend/config.py`), strict separation of `offers.csv` vs. `shops.category_names`, zero breaking changes to `UI_Template` JSON contracts (`backend/models/schemas.py`)

**Scale/Scope**: Designed to scale seamlessly from the 225,903-product / 331,506-offer hackathon dataset to 50M+ products and thousands of categories in Torob production

## Constitution Check

*GATE: Evaluated before Phase 0 research and re-verified after Phase 1 design.*

- **Principle 1 (300-Point Rubric & Beyond-Chat RTL UX)**: **PASS** — Preserves all `UI_Template` widgets (`FeatureClarificationCard`, `ComparisonView`, `StoresView`, `ShoppingCompanionModal`, `StoreContactModal`) and enriches product cards with explainable domain-trait match badges.
- **Principle 2 (Jev System One Decision Model & RecSys)**: **PASS (Evolved per User-Approved Simplification)** — Uses `Jev` (`Score`, `Noul`, `Choice`) with "Judgments in Jev, Decisions in Code", Anti-Fatigue Clarification (max 2 rounds), and Two-Layer Weight Normalization, while upgrading the 15-slot flat sum to the user-approved Two-Stage `Domain Trait Memory + 5 Orthogonal Store Criteria` model (documented in Complexity Tracking below).
- **Principle 3 (Torob Dataset Integrity & Transparency Guard)**: **PASS** — Enforces strict `offers.csv` vs. `shops.category_names` separation, `"null"` normalization, 112 real-shop badges, and indoor mall wayfinding.
- **Principle 4 (Ponytail Simplicity & Verification Discipline)**: **PASS** — Deletes fragile MAD/eviction complexity, reuses existing modules, and adds targeted self-checks in `backend/tests/`.
- **Principle 5 (Dual-Base Git Workflow & 3-Gate Approvals)**: **PASS** — Working on single-purpose branch `feature/002-jev-domain-recsys` off `develop`; all commits/pushes/PRs gated by explicit user approval.

## Project Structure

### Documentation (this feature)

```text
specs/002-jev-domain-recsys/
├── plan.md              # This implementation plan
├── research.md          # Phase 0 research decisions & mathematical rationale
├── data-model.md        # Phase 1 PostgreSQL + pgvector schema & entity model
├── quickstart.md        # Phase 1 end-to-end verification scenarios
├── contracts/
│   └── recsys-api.md    # Phase 1 System-One Jev & FastAPI REST contracts
└── checklists/
    └── requirements.md  # Specification quality checklist (16/16 passed)
```

### Source Code (repository root)

```text
backend/
├── config.py                # .env settings for 5 store criteria, decay scales & trait thresholds
├── main.py                  # FastAPI endpoints (/chat/turn + BackgroundTasks trait sync, /feedback)
├── db/
│   ├── postgres.py          # DDL adding user_trait_memory table & (user_id, domain) index
│   ├── profiles.py          # Domain-scoped pgvector trait read/upsert + 5-weight profile store
│   └── queries.py           # Hybrid pg_trgm + pgvector product search & offer retrieval
├── models/
│   └── schemas.py           # Backward-compatible Pydantic request/response models
├── recsys/
│   ├── jev_engine.py        # Parallel Jev turn evaluation, domain Choice, 3-level Scores & product re-ranker
│   ├── deduplicator.py      # Aspect-only embedding + pgvector filter + Jev Noul polarity-safe trait upsert
│   ├── weights.py           # Non-diluted Sparse Override fusion + contrastive UI feedback learning
│   ├── scorer.py            # Outlier-resistant 5-criteria store scorer + Hurdle Phi(i) + Pareto Top-3
│   └── clarifier.py         # 2-round Anti-Fatigue Clarification policy
└── tests/
    ├── test_recsys_math.py  # Unit tests for domain isolation, antonym update, and >=80% weight share
    └── test_api_endpoints.py# Integration tests for /chat/turn and /feedback
```

**Structure Decision**: Modify existing modules in `backend/` in-place with zero new top-level packages and zero breaking changes to `UI_Template/`.

## Complexity Tracking

| Modification vs. Initial Constitution v1 | Why Needed | Previous Design Replaced Because |
|------------------------------------------|------------|----------------------------------|
| Replace flat 15-slot vector (`5 Base + 5 Persona + 5 Global Dynamic Slots`) with **Stage 1 (`user_trait_memory` per `(user_id, domain)`) + Stage 2 (`5 Orthogonal Store Criteria`)** | Requested and approved by user to make the algorithm scientifically defensible and production-ready across arbitrary categories (`electronics` vs. `footwear_apparel`). | Flat 15-slot L1 normalization diluted a single explicit store preference to `18.4%`, mixed product specs with store distance, and evicted phone traits when searching for shoes. |
| Replace `confidence` ($\operatorname{MAD}$) gating with **3-Level Observability Rubric (`0: Not Mentioned, 1: Mild, 2: Primary`)** | Prevents wiping out user profile weights when a parameter is unmentioned (where a calibrated model is confident in Level 0). | Using `confidence` as a missingness gate violated TypeSafe's `SKILL.md` guidance and caused profile decay on urgent queries. |
