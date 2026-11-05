# Phase 0 Research & Architectural Decisions

**Feature**: `001-torob-shopping-assistant`  
**Date**: 2026-11-06  
**Detailed Mathematical Reference**: [`JEV_MODEL_AND_RECSYS_REPORT.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/JEV_MODEL_AND_RECSYS_REPORT.md)

---

## 1. Decision Log

### Decision 1: Backend & Data Engine (FastAPI + PostgreSQL + `pgvector` + Redis)
- **Decision**: Use **FastAPI (Python)** backed by **PostgreSQL + `pgvector`** as the primary relational, `JSONB`, trigram (`pg_trgm`), and vector (`vector(d)` HNSW) store for `dataset/shops.csv` (6,476 rows), `dataset/products.csv` (225,903 rows), `dataset/offers.csv` (331,506 rows), and `user_profiles`, paired with **Redis** for sub-millisecond session state, anti-fatigue clarification counters, hot user-profile caching, and geo/offer query caching.
- **Rationale**:
  - `dataset/` is 273 MB of UTF-8 CSVs with rich JSON columns (`specs`, `payment_options`, `weekly_hours`, `phones`, `warranty`). PostgreSQL `JSONB` with `GIN` indexes + `pg_trgm` handles structured and fuzzy Persian text filtering at scale.
  - **`pgvector`** natively powers both semantic product retrieval over `products` and **Stage-1 Embedding Cosine Similarity ($1 - (\mathbf{e}_{\text{new}} \Leftrightarrow \mathbf{e}_j) > 0.80$)** for deduplicating the 5 Dynamic Spec Slots (`slots 11..15`).
  - **Redis** keeps conversational `shopping_sessions`, active L1-normalized weight vectors $\hat{\mathbf{w}}$, and `clarification_count` anti-fatigue state in memory (`< 2 ms`), and both PostgreSQL (`pgvector`) and Redis have first-class managed service support on **Liara** for the final deployment phase.
- **Alternatives Considered**:
  - *Single-file SQLite / DuckDB*: Lacks concurrent multi-worker write scaling, native `pgvector` HNSW indexing, and distributed Redis TTL session caching.
  - *In-memory Pandas/CSV reload on startup*: Rejected—slow startup and high RAM usage.

### Decision 2: Decision Model & 15-Parameter Adaptive RecSys (`Jev` System One + Dual-Mode Adapter)
- **Decision**: Use TypeSafe AI's **`Jev` (`jev-1.14.0` / `jev-latest`)** via `typesafe-sdk` (`POST /v1/systemone`) to evaluate user intent, parameter weights (`Score`), dealbreakers/fitness/dissatisfaction (`Noul`), and category routing (`Choice`) in a single parallel request, paired with an automatic **OpenAI-compatible System-One Fallback Adapter** configured via `.env` (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`).
- **Rationale**:
  - `Jev` is trained via **RLCD** (*Reinforcement Learning for Calibrated Decisions*), returning calibrated discrete probability distributions and `confidence` $\in [0, 1]$ in $70\text{–}500\text{ ms}$.
  - Per-parameter `confidence` $c_k(q)$ acts as the exact mathematical precision gate in **Confidence-Gated Fusion** ($\tilde{w}_k = \alpha_k \hat{w}_k^{\text{session}} + (1 - \alpha_k) w_k^{\text{user}}$), solving the *Handsfree (Fast) vs. Phone (Cheap)* paradox without manual heuristics.
  - The Dual-Mode fallback guarantees 100% reliability in local testing and final-phase Liara deployment even if `TYPESAFE_API_KEY` is absent.
- **Alternatives Considered**:
  - *Collaborative Filtering / Matrix Factorization*: Impossible on Turn 1 because the Torob dataset contains zero historical user click/purchase logs.
  - *Multi-Agent LLM Debate Chain*: Rejected—adds $5\text{–}15\text{ s}$ latency and uncalibrated weight drift.

### Decision 3: Partitioned 15-Slot User Memory & Two-Layer Normalization
- **Decision**:
  - Partition the 15 parameters into **5 Global Base Slots** ($k \in \{1..5\}$), **5 Cross-Category Persona Slots** ($k \in \{6..10\}$), and **5 Dynamic Category/Session Spec Slots** ($k \in \{11..15\}$).
  - Store user weights **unconstrained in $[0, 1]^{15}$** in the database, and apply **L1-normalization ($\sum_{k=1}^{15} \hat{w}_k = 1$) only at query-time ranking**.
  - Deduplicate candidate dynamic features using **Stage-1 Embedding Cosine Similarity ($> 0.80$)** + **Stage-2 parallel `Jev` `Noul` equivalence check ($0.65\text{–}0.80$)**.
- **Rationale**: Prevents cross-category feature pollution (e.g., phone camera specs affecting shoe ranking), prevents weight dilution in the database when new slots are populated, and keeps the query-time utility $U(u, q, i) \in [0, 1]$ directly interpretable as a `0–100%` match badge.

### Decision 4: Frontend Architecture (`UI_Template` Preservation + Targeted Upgrades)
- **Decision**: Build directly on [`UI_Template/`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template) (React 19 + Vite + Tailwind CSS v4 + `motion/react` + `lucide-react`), keeping its dark raspberry-pink theme (`#0c0c10` / `#e9325a`), `TorobLogo`, `SearchingPapersAnimation`, and 3-tab + 2-modal layout, while replacing `server.ts` / `mockData.ts` with FastAPI endpoints and adding an open-source **Leaflet / MapLibre dark RTL map** in `StoresView`.
- **Rationale**: `UI_Template` already implements 80% of the visual widgets needed for the 150 UX/Product points. Wiring it to real data + Leaflet + indoor mall badges (`پاساژ / طبقه / واحد`) achieves maximum visual polish with minimal code churn.

### Decision 5: Step 4 Store Inquiry Strategy
- **Decision**: Skip automated live outbound voice calling for now; surface `last_price_changed_at` freshness badges, full contact details (`contacts` phone + real `instagram`/`website_url` for the 112 real shops) in `StoreContactModal.tsx`, the 4-step `ShoppingCompanionModal.tsx`, and 1-tap real backup store switching (`مغازه بسته بود؟ فروشگاه جایگزین`).
- **Rationale**: All 6,476 phone numbers in `shops.csv` are synthetic test numbers. Showing transparent price-update timestamps + 1-tap fallback + pre-call guidance delivers honest, zero-friction UX.
