# Phase 0 Research: Two-Stage Jev Recommender System & Domain-Scoped User Trait Memory

**Feature**: `002-jev-domain-recsys` | **Date**: 2026-11-12 | **Spec**: [spec.md](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/specs/002-jev-domain-recsys/spec.md)

---

## 1. Separation of Observability (`Mention Level`) from Distribution `confidence` in TypeSafe `Jev`

- **Decision**: Use a 3-level ordered `Score` rubric (`0: Not Mentioned`, `1: Mild Preference`, `2: Primary Priority`) for each of the 5 store criteria (`w_price`, `w_distance`, `w_open_now`, `w_trust_freshness`, `w_installment`), rather than using `Jev`'s distribution `confidence` ($\operatorname{MAD}$) as a proxy for whether the user mentioned a criterion.
- **Rationale**: Per TypeSafe AI's engineering guide (`.agents/skills/typesafe-ai/SKILL.md`), `confidence` measures probability concentration around the mode, not epistemic observability. When a user does not mention a feature, a calibrated model assigns high probability to Level 0 (`Not Mentioned`), producing **high `confidence`** (`~0.90`). Using `confidence` as a fusion gate erroneously overwrote long-term user weights with zeros. Explicitly encoding `Level 0 = Not Mentioned` lets code apply a deterministic truth-table rule (`score / 2.0 >= 0.35` $\implies$ active session preference; else fallback to tie-breaker weight).
- **Alternatives Considered**:
  - *MAD-based confidence gating*: Rejected due to mathematical discontinuity around $\operatorname{mode}(p)$, boundary bias against levels `0` and `4`, and conflation of "confident it wasn't mentioned" with "uncertain."
  - *Dual `Noul` + `Score` per criterion (10 questions)*: Valid theoretically, but a 3-level situational `Score` achieves the exact same observability separation in 5 questions instead of 10.

---

## 2. Production-Grade Domain-Scoped Trait Memory (`(Domain, Aspect, Preference)`) vs. Static Category Schemas

- **Decision**: Store specialized product preferences in a dedicated PostgreSQL + `pgvector` table (`user_trait_memory`) partitioned by `(user_id, domain)` where **only `aspect`** (the attribute axis, e.g., `"وزن و قابلیت حمل دستگاه"` or `"ارگونومی و ساختار کفی"`) is embedded into `aspect_embedding vector(dim)`, while **`preference`** (the user's directional stance, e.g., `"سبک"` vs. `"بدنه سنگین و مقاوم"`) is stored as a separate column.
- **Rationale**:
  1. **Catalog & Dataset Independence**: Works identically on the 225,903-product hackathon sample and on Torob's 50M-product production catalog without hardcoding CSV category trees or brittle `specs` keys.
  2. **Eliminates Antonym / Polarity Collisions**: Embedding full phrases like `"گوشی سبک"` and `"گوشی سنگین"` yields cosine similarity `> 0.82`, causing naive vector deduplicators to merge opposites. By embedding only `aspect` (`"وزن و ابعاد دستگاه"`) and confirming borderline matches (`cosine >= 0.60`) via a parallel `Jev` `Noul` question (*"Do aspect_A and aspect_B describe the same product attribute?"*), a change in user viewpoint updates the existing row's `preference` in-place rather than creating duplicate or conflicting slots.
  3. **Sub-Domain Relevance at Scale**: Within a broad domain like `electronics`, ordering by `aspect_embedding <=> query_embedding LIMIT 5` retrieves only the 5 traits relevant to the current item (e.g., audio latency traits when searching for headphones, camera traits when searching for phones) while keeping `footwear_apparel` 100% isolated.
- **Alternatives Considered**:
  - *5 Global Dynamic Slots (`user_dynamic_slots` with `slot_id 11..15`)*: Rejected because switching from a phone search to a shoe search caused cross-category pollution or evicted phone preferences.
  - *Static `products.specs` dictionary mapping*: Rejected because merchant `specs` in production are sparse/inconsistent across thousands of evolving leaf categories.

---

## 3. Zero-Latency Online Read vs. Asynchronous Background Write (`FastAPI BackgroundTasks`)

- **Decision**: Decouple trait retrieval (synchronous online read, `< 2 ms` via `pgvector` reusing the query embedding) from trait extraction, deduplication, and persistence (asynchronous write via `FastAPI BackgroundTasks` after `ChatTurnResponse` is returned).
- **Rationale**: Deduplicating new traits requires embedding the candidate `aspect`, querying `pgvector`, and optionally calling `Jev` `Noul` to verify equivalence. Running this on the write path in `BackgroundTasks` adds **0 ms** to user-perceived chat latency while keeping p95 turn latency under `600 ms`.
- **Alternatives Considered**:
  - *Synchronous inline upsert before ranking*: Adds `150–350 ms` to every turn even though newly extracted traits are already present in the current turn's `req.message`.

---

## 4. Two-Stage Decoupled Ranking & Outlier-Resistant Store Utility Math

- **Decision**: Separate **Stage 1 (Product Selection)** from **Stage 2 (Physical Store Ranking)** and score physical store offers using 5 mutually independent criteria with relative exponential price decay $f_{i,1} = \exp\!\left(-\frac{P_i - P_{\min}}{0.15 \cdot P_{\min}}\right)$ and sparse L1 weight normalization.
- **Rationale**:
  - In Multi-Attribute Utility Theory (MAUT), mixing 10 store/persona weights and 5 product spec weights in a single 15-term denominator diluted a user's single explicit store priority (e.g., *"ارزان‌ترین"*) to `~18.4%`. With 5 store criteria and a `0.10` tie-breaker multiplier on unmentioned criteria, a single explicit priority receives `> 80%` weight (`SC-001`).
  - Relative exponential decay anchored at the market floor price $P_{\min}$ is invariant to extreme high-price outliers and prevents amplifying trivial `< 0.5%` price differences (unlike Min-Max normalization).
  - Removing the separate `travel_penalty` subtraction eliminates double-counting between `w_distance` and `w_price`.
- **Alternatives Considered**:
  - *Min-Max price normalization with additive travel-cost penalty*: Rejected due to outlier vulnerability and violation of preferential independence.

---

## 5. Revealed-Preference Contrastive Update for Store Weights

- **Decision**: Never mutate long-term store weights `user_profiles` from chat text; update them only on explicit UI feedback (`/api/v1/feedback`) proportionally to $(f_{\text{selected}, k} - \bar{f}_{\text{shown}, k})$.
- **Rationale**: Chat text expresses situational urgency (e.g., needing a charger immediately today), whereas UI clicks/selections express revealed preference. Subtracting the mean of shown stores $\bar{f}_{\text{shown}, k}$ debias position/presentation effects so attributes shared by all displayed stores (e.g., all shown stores are open) do not artificially inflate their weight.
- **Alternatives Considered**:
  - *Prompt-driven EMA on every chat turn*: Rejected because urgent one-off queries permanently skewed the user's baseline profile.
