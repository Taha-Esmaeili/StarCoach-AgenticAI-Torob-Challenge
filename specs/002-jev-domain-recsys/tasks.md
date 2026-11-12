---

description: "Task list for Two-Stage Jev Recommender System with Domain-Scoped User Trait Memory"
---

# Tasks: Two-Stage Jev Recommender System with Domain-Scoped User Trait Memory

**Input**: Design documents from `/specs/002-jev-domain-recsys/` (`plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/recsys-api.md`, `quickstart.md`)

**Prerequisites**: `plan.md` (required), `spec.md` (required for user stories), `research.md`, `data-model.md`, `contracts/recsys-api.md`

**Tests**: Included per project constitution (`/ponytail` mandatory verification check for all non-trivial RecSys math and API behavior).

**Organization**: Tasks are grouped by user story (`US1`, `US2`, `US3`) to enable independent implementation and verification of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (`[US1]`, `[US2]`, `[US3]`)
- Exact repository file paths are included in every task description

## Path Conventions

- **Backend application**: `backend/`, `backend/db/`, `backend/recsys/`, `backend/models/`, `backend/tests/`
- **Specs & Docs**: `specs/002-jev-domain-recsys/`, `JEV_MODEL_AND_RECSYS_REPORT.md`

---

## Phase 1: Setup (Shared Configuration & Environment Hyperparameters)

**Purpose**: Configure `.env`-driven settings and constants required across both stages of the Jev recommender engine.

- [X] T001 Add 5-criteria store weight defaults (`w_price`, `w_distance`, `w_open_now`, `w_trust_freshness`, `w_installment` in `[0.10, 1.00]^5`, default `0.30` each), decay scales (`recsys_price_decay_ratio = 0.15`, `recsys_distance_decay_km = 8.0`), sparse override constants (`recsys_mention_score_threshold = 0.35`, `recsys_unmentioned_tiebreaker_factor = 0.10`), and domain trait memory thresholds (`recsys_trait_cosine_candidate_threshold = 0.60`, `recsys_trait_jev_same_aspect_noul = 0.70`, `recsys_max_traits_per_query = 5`) in `backend/config.py`
- [X] T002 [P] Add `.obsidian/` to `.gitignore` to keep the working tree clean per `/git-workflow` pre-flight hygiene in `.gitignore`

---

## Phase 2: Foundational (Database Schema & Dual-Mode Embedding / System-One Primitives)

**Purpose**: Core database schema (`user_trait_memory`) and `Jev` / embedding primitives that MUST be complete before user story phases.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 Add `user_trait_memory` table DDL (`trait_id BIGSERIAL PRIMARY KEY`, `user_id TEXT NOT NULL REFERENCES user_profiles(user_id) ON DELETE CASCADE`, `domain TEXT NOT NULL`, `aspect TEXT NOT NULL`, `preference TEXT NOT NULL`, `aspect_embedding vector({dim})`, `hit_count INTEGER NOT NULL DEFAULT 1`, `updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`) and composite index `idx_user_trait_memory_user_domain ON user_trait_memory (user_id, domain)` in `backend/db/postgres.py`
- [X] T004 [P] Implement `embed_text_async(text: str)` in `backend/recsys/jev_engine.py` supporting live OpenAI-compatible `/embeddings` (`settings.effective_embedding_base_url`) with automatic fallback to `deterministic_text_embedding(text)` when no embedding API key is configured, including domain-concept synonym groups for both digital electronics and footwear/apparel in `backend/recsys/jev_engine.py`
- [X] T005 Define `VALID_DOMAINS` (`electronics | footwear_apparel | home_kitchen | sports_outdoors | beauty_health | tools_auto | culture_toys | general`), `ExtractedDomainTrait` dataclass (`domain: str`, `aspect: str`, `preference: str`, `is_durable: bool = True`), and updated `SystemOneTurnEvaluation` fields (`domain: str`, `needs_clarification: NoulJudgment`, `extracted_traits: list[ExtractedDomainTrait]`) in `backend/recsys/jev_engine.py`

**Checkpoint**: Foundation ready — `user_trait_memory` DDL and core `Jev`/embedding types are in place.

---

## Phase 3: User Story 1 - Domain-Isolated Specialized Product Discovery & Trait Memory (Priority: P1) 🎯 MVP

**Goal**: Enable per-user, per-domain specialized product preference memory (`(user_id, domain, aspect, preference)`) with aspect-only vector retrieval (`< 2 ms` online read), polarity-safe background deduplication (`0 ms` user wait via `FastAPI BackgroundTasks`), and Stage-1 product re-ranking.

**Independent Test**: Send a turn for `user_1` in `electronics` (e.g., battery/gaming traits) and a turn in `footwear_apparel` (e.g., orthopedic insole trait); verify `electronics` traits personalize subsequent digital searches, never leak into shoe searches (`SC-002`), and opposite preferences on the same `aspect` (e.g., `"سبک"` $\rightarrow$ `"سنگین و صنعتی"`) update the existing record in-place (`SC-003`).

### Implementation for User Story 1

- [X] T006 [P] [US1] Implement `fetch_domain_traits_pgvector(pg_pool, user_id, domain, query_embedding, limit=5)` and `find_closest_domain_aspects_pgvector(pg_pool, user_id, domain, aspect_embedding, limit=3)` with in-memory fallback (`_MEMORY_TRAITS`) for unit test isolation in `backend/db/profiles.py`
- [X] T007 [US1] Implement domain classification (`domain` `Choice` across `electronics | footwear_apparel | home_kitchen | sports_outdoors | beauty_health | tools_auto | culture_toys | general`), durability filtering (`is_durable`), and open-vocabulary `(aspect, preference)` extraction in `evaluate_turn_with_jev` and `check_same_aspect_noul(aspect_a, aspect_b)` in `backend/recsys/jev_engine.py`
- [X] T008 [US1] Implement polarity-safe `sync_user_domain_traits(user_id, domain, extracted_traits, pg_pool)` in `backend/recsys/deduplicator.py` that embeds only `aspect`, checks `pgvector` cosine similarity (`>= 0.60`), confirms via `check_same_aspect_noul` (`noul >= 0.70`), and updates `preference` in-place on match or inserts a new row (while keeping `upsert_dynamic_spec_slots` wrapper for backward compatibility) in `backend/recsys/deduplicator.py`
- [X] T009 [P] [US1] Enhance `search_products` in `backend/db/queries.py` and add Stage-1 `rerank_products_with_domain_traits(query, domain_traits, raw_products)` so candidate products matching current query and stored domain traits are boosted and surface matched traits in `RecommendedProductItem.best_for_fa` / `pros_fa` in `backend/db/queries.py` and `backend/main.py`
- [X] T010 [US1] Wire synchronous `fetch_domain_traits_pgvector` read and non-blocking `BackgroundTasks.add_task(sync_user_domain_traits, ...)` write into `post_chat_turn` in `backend/main.py`
- [X] T011 [US1] Add unit tests in `backend/tests/test_recsys_math.py` verifying: (a) 100% isolation between `electronics` and `footwear_apparel` traits (`SC-002`), (b) antonym/polarity update on the same `aspect` without creating duplicate traits (`SC-003`), and (c) durability filtering of one-off phrases in `backend/tests/test_recsys_math.py`

**Checkpoint**: User Story 1 is independently functional and verified.

---

## Phase 4: User Story 2 - Non-Diluted 5-Criteria Physical Store Ranking & Dealbreaker Filtering (Priority: P1)

**Goal**: Rank physical store offers from `offers.csv` using 5 mutually independent criteria (`w_price`, `w_distance`, `w_open_now`, `w_trust_freshness`, `w_installment`) with a 3-level `Jev` `Score` rubric (`0: Not Mentioned, 1: Mild, 2: Primary`), Sparse Override weighting (`>= 80%` weight on a single mentioned criterion), outlier-resistant exponential price decay, and Dealbreaker Hurdle multipliers.

**Independent Test**: Send a query emphasizing only price (*"ارزان‌ترین فروشگاه گوشی A55"*); verify `w_price >= 0.80` after L1 normalization (`SC-001`), verify extreme high-price outlier stores do not distort price scores among normal stores, and verify Pareto Top-3 badges (`best_overall`, `closest_open`, `lowest_price`) are assigned.

### Implementation for User Story 2

- [X] T012 [P] [US2] Update `evaluate_turn_with_jev` in `backend/recsys/jev_engine.py` to evaluate the 5 orthogonal store criteria (`w_price`, `w_distance`, `w_open_now`, `w_trust_freshness`, `w_installment`) on the 3-level observability rubric (`score / 2.0 in [0.0, 1.0]`, where `< 0.35` means unmentioned in chat) in `backend/recsys/jev_engine.py`
- [X] T013 [US2] Update `fuse_and_normalize_weights` in `backend/recsys/weights.py` to implement Sparse Override fusion (`s_k >= 0.35` receives direct weight `s_k`; unmentioned criteria receive `0.10 * p_k(u)` tie-breaker weight when at least one criterion is mentioned, or `p_k(u)` when none are mentioned) and L1-normalize across the 5 store criteria (`sum == 1.0`) while preserving legacy key aliases in `backend/recsys/weights.py`
- [X] T014 [US2] Update `_compute_feature_vector` and `score_and_rank_offers` in `backend/recsys/scorer.py` to compute outlier-resistant relative exponential price score `exp(-(P_i - P_min) / (0.15 * P_min))`, distance score `exp(-d_i / 8.0)`, open-now score, composite trust & freshness score `0.65 * exp(-age_days / 14.0) + 0.20 * I(is_real_shop) + 0.15 * I(has_warranty)`, and in-person installment score without double-counting travel cost in `backend/recsys/scorer.py`
- [X] T015 [US2] Add unit tests in `backend/tests/test_recsys_math.py` verifying: (a) single-criterion mention achieves `>= 0.80` normalized weight (`SC-001`), (b) outlier price invariance on `f_{i,1}`, and (c) Dealbreaker Hurdle `Phi(i) = 0.15` demotion in `backend/tests/test_recsys_math.py`

**Checkpoint**: User Stories 1 and 2 are both independently functional and verified.

---

## Phase 5: User Story 3 - Anti-Fatigue Clarification & Revealed-Preference UI Feedback Learning (Priority: P2)

**Goal**: Trigger `FeatureClarificationCard` via `Jev` `needs_clarification` `Noul` at most once initially (and once on dissatisfaction, hard cap 2), keep stored `user_profiles` immune to emergency chat text (`SC-005`), and update store weights on `/api/v1/feedback` using contrastive revealed-preference deltas `(f_selected - mean(f_shown))`.

**Independent Test**: Send an emergency distance query in `/api/v1/chat/turn` and verify `user_profiles.base_weights` does not change (`SC-005`); then call `/api/v1/feedback` and verify `user_profiles.base_weights` updates contrastively without inflating attributes that are identical across all shown stores.

### Implementation for User Story 3

- [X] T016 [P] [US3] Update `should_trigger_clarification` in `backend/recsys/clarifier.py` to support `needs_clarification` `Noul` (`>= 0.70` or `effective_confidence < 0.45`) on Turn 1 (`clarification_count == 0 -> 1`) and `user_dissatisfied` `Noul >= 0.70` / `thumbs_down` on retry (`1 -> 2`, capped at `2`) in `backend/recsys/clarifier.py`
- [X] T017 [US3] Implement `update_store_weights_contrastive(user_profile, selected_offer, shown_offers, explicit_deltas)` in `backend/recsys/weights.py` applying `p_k <- clip(p_k + 0.15 * (f_selected_k - mean_shown_k), 0.10, 1.00)` and remove prompt-driven profile mutation from `post_chat_turn` in `backend/main.py` and `backend/recsys/weights.py`
- [X] T018 [US3] Add integration tests in `backend/tests/test_api_endpoints.py` verifying emergency chat turns do not mutate long-term store weights (`SC-005`), `/api/v1/feedback` updates weights and re-ranks stores, and anti-fatigue clarification caps at 2 rounds in `backend/tests/test_api_endpoints.py`

**Checkpoint**: All three user stories (`US1`, `US2`, `US3`) are complete and independently verified.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Synchronize technical documentation with the simplified two-stage architecture and run the full test suite.

- [X] T019 [P] Update `JEV_MODEL_AND_RECSYS_REPORT.md` and `RECSYS_DOCUMENTATION.md` to reflect the production-grade Two-Stage Jev Architecture (`Domain-Scoped Trait Memory` + `5 Orthogonal Store Criteria`) in `JEV_MODEL_AND_RECSYS_REPORT.md` and `RECSYS_DOCUMENTATION.md`
- [X] T020 Run full verification suite (`uv run pytest backend/tests/ -v`) as specified in `specs/002-jev-domain-recsys/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1: `T001–T002`)**: No dependencies — can start immediately.
- **Foundational (Phase 2: `T003–T005`)**: Depends on `T001` — blocks all user story phases.
- **User Story 1 (Phase 3: `T006–T011`, P1 🎯 MVP)**: Depends on Phase 2 (`T003–T005`).
- **User Story 2 (Phase 4: `T012–T015`, P1)**: Depends on Phase 2 (`T003–T005`); can execute in parallel with `T006` and `T008` of `US1`.
- **User Story 3 (Phase 5: `T016–T018`, P2)**: Depends on `T013` (`US2` weight manager).
- **Polish (Phase 6: `T019–T020`)**: Depends on completion of `US1`, `US2`, and `US3`.

### Parallel Opportunities

- `T001` (`backend/config.py`) and `T002` (`.gitignore`) can run in parallel.
- `T003` (`backend/db/postgres.py`) and `T004` (`backend/recsys/jev_engine.py`) can run in parallel.
- Once Phase 2 completes, `T006` (`backend/db/profiles.py`), `T009` (`backend/db/queries.py`), `T014` (`backend/recsys/scorer.py`), and `T016` (`backend/recsys/clarifier.py`) touch distinct files and can be developed in parallel.

---

## Parallel Example: User Story 1 & User Story 2

```bash
# Parallel persistence & query layer tasks across distinct files:
Task T006: "Implement fetch_domain_traits_pgvector and find_closest_domain_aspects_pgvector in backend/db/profiles.py"
Task T009: "Enhance search_products and Stage-1 trait re-ranking in backend/db/queries.py"
Task T014: "Implement outlier-resistant 5-criteria store scorer in backend/recsys/scorer.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 + User Story 2 Core)

1. Complete Phase 1 (`T001–T002`) and Phase 2 (`T003–T005`).
2. Complete Phase 3 (`US1: T006–T011`) to deliver domain-isolated trait memory and personalized product selection.
3. Complete Phase 4 (`US2: T012–T015`) to deliver non-diluted 5-criteria physical store ranking.
4. Complete Phase 5 (`US3: T016–T018`) and Phase 6 (`T019–T020`), then run `uv run pytest backend/tests/ -v`.
