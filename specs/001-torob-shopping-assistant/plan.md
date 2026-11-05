# Implementation Plan: Torob Smart In-Person Shopping Assistant (دستیار هوشمند خرید حضوری ترب)

**Branch**: `001-torob-shopping-assistant` | **Date**: 2026-11-06 | **Spec**: [`spec.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/specs/001-torob-shopping-assistant/spec.md)  
**Input**: Feature specification from [`specs/001-torob-shopping-assistant/spec.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/specs/001-torob-shopping-assistant/spec.md) & RecSys mathematical specification from [`JEV_MODEL_AND_RECSYS_REPORT.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/JEV_MODEL_AND_RECSYS_REPORT.md).

---

## Summary

We are building **Torob's Smart In-Person Shopping Assistant (ترب‌چیت حضوری)** for physical retail stores in Tehran, engineered to maximize the **300-point hackathon rubric**:
1. **UX Beyond Chat (150 pts — Product + UX)**: Extends the user-provided [`UI_Template/`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template) (React 19 + Vite + Tailwind v4, dark raspberry-pink `#0c0c10`/`#e9325a` theme, 8-bit `TorobLogo`, `SearchingPapersAnimation`, `Vazirmatn` RTL) with a real dark-mode **Leaflet/MapLibre** map (`InteractiveMap.tsx`), a 1-tap anti-fatigue clarification card (`FeatureClarificationCard.tsx`), dynamic category spec comparison (`ComparisonMatrix.tsx`), and an indoor mall micro-guide + 1-tap backup store switcher (`ShoppingCompanionModal.tsx`).
2. **15-Parameter Adaptive RecSys & Jev Decision Engine (50 pts — Intelligence)**: Implements the scientifically grounded **15-Parameter Adaptive Utility Engine** (`5 Global Base + 5 Persona + 5 Dynamic Category/Session Spec` slots) powered by TypeSafe AI's **`Jev` (`jev-1.14.0`) System One model** (`Choice`, `Score`, `Noul`, `Box`) with automatic OpenAI-compatible System-One fallback. Features **Two-Layer Weight Normalization** (unconstrained $[0, 1]^{15}$ PostgreSQL/Redis storage + query-time L1 simplex normalization $\sum \hat{w}_k = 1$), **Confidence-Gated Fusion**, **Hybrid `pgvector` Cosine ($>0.80$) + `Jev` `Noul` ($0.65\text{–}0.80$) Deduplication**, **Hard-Constraint Dealbreaker Hurdles** ($\Phi(i)$), **Value-of-Travel Coupling**, and **Pareto-Front Top-3 Diversity**.
3. **Sub-Second PostgreSQL + `pgvector` (+ Redis) Data Engine (60 pts — Technical + Dataset Mastery)**: Indexes `shops.csv` (`6,476`), `products.csv` (`225,903`), and `offers.csv` (`331,506`) into **PostgreSQL 16+ (`pgvector` + `pg_trgm` + `JSONB` GIN)** paired with **Redis 7+** (`< 2 ms` session state, anti-fatigue counters & hot profile/query caching). Enforces Persian text normalization, strict separation of `offers.csv` stock vs. `shops.category_names` fallback, JSONB parsing for `weekly_hours`, `payment_options`, and `warranty`, and regex extraction of Tehran indoor mall coordinates (`پاساژ`/`طبقه`/`واحد`).
4. **Final Phase Only — Liara Deployment & 5-Min Demo Video (40 pts + Mandatory Deliverable)**: Containerized deployment on Liara (connecting to managed PostgreSQL/`pgvector` and Redis) is strictly deferred to the **final phase (Phase 7)** after all local UX, RecSys, and dataset features are complete and verified.

---

## Technical Context

**Language/Version**: TypeScript 5.8 (Frontend React 19 + Vite 6) & Python 3.11+ (Backend FastAPI)  
**Primary Dependencies**:
- **Frontend (`UI_Template/`)**: `react@19`, `tailwindcss@4`, `motion`, `lucide-react`, `leaflet` / `react-leaflet` (dark OSM/CartoDB tiles)
- **Backend (`backend/`)**: `fastapi`, `uvicorn`, `asyncpg` / `psycopg[binary]`, `pgvector`, `redis`, `pydantic`, `openai` (OpenAI-compatible client), `typesafe-sdk` (TypeSafe AI `Jev` client), `numpy`
**Storage**: **PostgreSQL 16+ (`pgvector` + `pg_trgm`)** + **Redis 7+** (local `docker-compose.yml` for dev; managed Liara PostgreSQL + Redis in Phase 7) populated from `dataset/*.csv` (`273 MB`, git-ignored)  
**Testing**: `pytest` + `pytest-asyncio` (backend self-checks & RecSys math assertions) + TypeScript build checks (`npm run lint && npm run build`)  
**Target Platform**: Local development first; Dockerized Linux container on **Liara** strictly in the final phase  
**Project Type**: Full-stack Web Application (Mobile-first Persian RTL Generative UI + FastAPI + PostgreSQL/`pgvector` + Redis + Jev Backend)  
**Performance Goals**: `< 50 ms` PostgreSQL (`pgvector` + `pg_trgm`) / `< 5 ms` Redis cached retrieval; `< 450 ms` parallel `Jev` System One scoring; `< 1.5 s` end-to-end turn latency  
**Constraints**: Strict adherence to `/git-workflow` (atomic single-purpose branches targeting `develop`, 3-gate user approval), `/ponytail` (smallest complete solution, zero bloat), and `/deep-interview` (consultant verification).

---

## Constitution Check

*GATE: Verified against [`.specify/memory/constitution.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/.specify/memory/constitution.md).*

- [x] **I. Beyond-Chat Persian RTL Generative UX**: Preserves `UI_Template/` dark raspberry-pink theme and renders structured interactive cards, sliders, and map pins instead of wall-of-text chat.
- [x] **II. Dataset Mastery & Offer-vs-Category Separation**: `offers.csv` (`331,506` rows) is the primary stock source; `shops.category_names` is strictly isolated as an explicit labeled fallback (`is_category_fallback`).
- [x] **III. Explainable 15-Parameter Adaptive RecSys & Jev Engine**: Implements `5+5+5` slot partitioning, Two-Layer Normalization, Confidence-Gated Fusion, Hybrid `pgvector` + `Jev` `Noul` Deduplication, and Anti-Fatigue Clarification (max 1 prompt initially; 1 retry only on explicit dissatisfaction).
- [x] **IV. Sub-Second Data Engine & Liara-Last Discipline**: PostgreSQL (`pgvector` + `pg_trgm`) + Redis handles sub-second filtering and session state; Liara deployment is isolated to the final phase.
- [x] **V. Governance (`AGENTS.md`)**: Follows `/deep-interview`, `/ponytail`, and `/git-workflow`.

---

## Project Structure

### Documentation (this feature)

```text
specs/001-torob-shopping-assistant/
├── constitution.md      # Project constitution & rubric alignment
├── spec.md              # Feature specification (US1-US5, FR-001..FR-012)
├── plan.md              # This implementation plan
├── research.md          # Phase 0 architectural & empirical dataset findings
├── data-model.md        # PostgreSQL + pgvector + Redis schemas & 15-slot profile schema
├── quickstart.md        # Local execution & verification scenarios
├── contracts/
│   └── api.md           # REST API & Generative UI widget contracts
└── tasks.md             # Actionable, dependency-ordered task list
```

### Source Code (repository root)

```text
Torob/
├── AGENTS.md                        # Master agent rules & skill registry
├── JEV_MODEL_AND_RECSYS_REPORT.md   # Mathematical & Jev System One specification
├── ROADMAP.md                       # Visual phase & branch roadmap
├── docker-compose.yml               # Local PostgreSQL (pgvector:pg16) + Redis (redis:7-alpine)
├── .agents/skills/                  # Project-specific skills
│   ├── beyond-chat-rtl-ux/SKILL.md
│   ├── torob-dataset-guard/SKILL.md
│   ├── typesafe-ai/SKILL.md
│   └── speckit-teamwork/SKILL.md
├── backend/                         # FastAPI + PostgreSQL (pgvector) + Redis + Jev 15-Param Engine
│   ├── main.py                      # FastAPI app, CORS, static serving, /api/v1 routes
│   ├── config.py                    # .env loader (DATABASE_URL, REDIS_URL, LLM_*, TYPESAFE_API_KEY)
│   ├── db/
│   │   ├── postgres.py              # asyncpg pool, pgvector/pg_trgm DDL & migrations
│   │   ├── redis_cache.py           # Redis client for sessions, anti-fatigue counter & query cache
│   │   ├── ingest.py                # Fast CSV COPY -> PostgreSQL, mall regex, "null" cleaning
│   │   ├── queries.py               # Sub-second Haversine + pg_trgm + pgvector + stock/fallback SQL
│   │   └── profiles.py              # user_profiles, user_dynamic_slots (pgvector) & Redis write-through
│   ├── recsys/
│   │   ├── jev_engine.py            # Dual-mode TypeSafe Jev SDK + OpenAI System-One fallback
│   │   ├── weights.py               # 5+5+5 slots, Two-Layer L1 norm, Confidence-Gated Fusion
│   │   ├── deduplicator.py          # Hybrid pgvector (<=> >0.80) + Jev Noul (0.65-0.80) dedup
│   │   ├── scorer.py                # Hurdle Phi(i), travel coupling, Pareto Top-3 selector
│   │   └── clarifier.py             # Anti-fatigue 1-time clarification & dissatisfaction gate
│   ├── models/
│   │   └── schemas.py               # Pydantic request/response contracts matching contracts/api.md
│   └── tests/
│       ├── test_ingest_guard.py     # Dataset integrity & offer-vs-category assertions
│       └── test_recsys_math.py      # L1 simplex, EMA, hurdle, and anti-fatigue unit tests
└── UI_Template/                     # React 19 + Vite + Tailwind v4 Frontend
    ├── src/
    │   ├── App.tsx                  # Main RTL shell, live API integration, ThumbsUp/Down loop
    │   ├── api/client.ts            # Typed client for /api/v1/* endpoints
    │   └── components/
    │       ├── StoreCard.tsx                # Enhanced with Why-This-Shop, Mall & Freshness badges
    │       ├── FeatureClarificationCard.tsx # Anti-fatigue 1-tap priority clarifier widget
    │       ├── InteractiveMap.tsx           # Upgraded to live Leaflet dark RTL map with price pins
    │       ├── ComparisonMatrix.tsx         # Upgraded to dynamic category specs + live Tehran stock
    │       ├── ShoppingCompanionModal.tsx   # Upgraded with Mall Micro-Guide & 1-Tap Fallback rescue
    │       ├── StoreContactModal.tsx        # Real shop phone, Instagram/Web badges, freshness alert
    │       └── ProfilePrioritiesModal.tsx   # Bound to live 15-parameter user_profiles vector
    └── package.json
```

---

## Phased Execution Strategy (Aligned with `/git-workflow`)

| Phase | Target Branch (`from develop`) | Core Deliverable | Rubric Impact |
| :--- | :--- | :--- | :--- |
| **Phase 1: Setup & Contracts** | `feature/p1-backend-skeleton` | `docker-compose.yml` (`pgvector:pg16` + `redis:7-alpine`), Python `backend/` structure, `.env.example`, Pydantic contracts (`schemas.py`), FastAPI `/api/v1/health`. | Technical (15 pts) |
| **Phase 2: PostgreSQL (`pgvector`) + Redis Data Engine** | `feature/p2-postgres-pgvector-redis` | `ingest.py`, `queries.py`, `redis_cache.py`: index `6,476` shops, `225,903` products, `331,506` offers into PostgreSQL (`pgvector` + `pg_trgm` + `JSONB`); mall regex (`پاساژ`/`طبقه`/`واحد`); `"null"` guard; Redis session & query cache. | Dataset Mastery (20 pts) + Technical (25 pts) |
| **Phase 3: Jev 15-Param RecSys** | `feature/p3-jev-recsys-engine` | `jev_engine.py`, `weights.py`, `deduplicator.py`, `scorer.py`, `clarifier.py`: `5+5+5` slots, Two-Layer L1 norm, `pgvector` `<=>` + `Jev` `Noul` dedup, Hurdle $\Phi(i)$, Travel coupling, Pareto Top-3, Anti-fatigue gate. | Intelligence (50 pts) |
| **Phase 4: Conversational API & Clarifier UX (`US1`)** | `feature/p4-need-discovery-ux` | Connect `App.tsx`, `FeatureClarificationCard.tsx`, `ProfilePrioritiesModal.tsx`, and 👍/👎 feedback loop to `/api/v1/chat/turn` and `/api/v1/feedback`. | Product (35 pts) + UX Beyond Chat (25 pts) |
| **Phase 5: Geo-Store Ranking & Leaflet Map (`US2`)** | `feature/p5-leaflet-map-stores` | Upgrade `InteractiveMap.tsx` (real Leaflet dark RTL map + custom price pins + route preview) and `StoreCard.tsx` (Why-This-Shop pills, installment/warranty/verified badges). | UX Beyond Chat (30 pts) |
| **Phase 6: Dynamic Comparison & Mall Companion (`US3` & `US4`)** | `feature/p6-compare-and-companion` | Upgrade `ComparisonMatrix.tsx` (`/api/v1/products/compare`) and `ShoppingCompanionModal.tsx` (Indoor Mall Micro-Guide + 1-Tap Fallback `/api/v1/stores/{id}/fallback`). | Product (40 pts) + UX Beyond Chat (20 pts) |
| **Phase 7: Final Phase — Liara Deployment & Demo Video (`US5`)** | `feature/p7-liara-deployment` $\rightarrow$ `release/v1.0.0` | `Dockerfile`, `liara.json` (linked to Liara PostgreSQL/`pgvector` + Redis), production deployment verification, and 5-minute Demo Video script & recording. | Deployment (40 pts) + Mandatory Video |

---

## Complexity Tracking

| Design Choice | Why Needed | Simpler Alternative Rejected Because |
| :--- | :--- | :--- |
| **PostgreSQL + `pgvector` (+ Redis)** | Combines relational joins (`offers` $\bowtie$ `shops`), `JSONB` GIN indexing, `pg_trgm` Persian fuzzy search, `pgvector` HNSW cosine similarity (`<=>`) for Stage-1 dynamic slot deduplication & semantic search, and `<2ms` Redis session/anti-fatigue caching. | Single-file databases lack concurrent multi-worker scaling, native `pgvector` HNSW indexes, and distributed Redis TTL session caching. |
| **Two-Layer Weight Normalization** (Unconstrained $[0,1]^{15}$ in PostgreSQL/Redis + L1 Simplex $\sum \hat{w}_k = 1$ at query time) | Prevents cross-turn weight dilution when updating a single parameter while guaranteeing scale-invariant utility $U \in [0, 1]$ across turns. | Storing L1-normalized weights directly in the DB shrinks all historical preferences whenever a new session feature spikes. |
| **Dual-Mode `Jev` Engine** (`typesafe-sdk` + OpenAI-compatible System-One fallback) | Delivers authentic TypeSafe System One (`Score`, `Noul`, `Choice`) logprob calibration while guaranteeing 100% uptime with standard `.env` LLM credentials. | Relying on a single external API key risks failure during live hackathon evaluation. |
