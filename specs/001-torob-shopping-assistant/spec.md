# Feature Specification: Torob Smart In-Person Shopping Assistant (ترب‌چیت حضوری)

**Feature Branch**: `001-torob-shopping-assistant`  
**Created**: 2026-11-06  
**Status**: Approved for Planning  
**Input**: [`CHALLENGE.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/CHALLENGE.md), [`UI_Template/`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template), and [`JEV_MODEL_AND_RECSYS_REPORT.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/JEV_MODEL_AND_RECSYS_REPORT.md)

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Need Discovery, Anti-Fatigue Clarification & Jev 15-Parameter RecSys (Priority: P1) 🎯 MVP

A Tehran shopper enters a natural-language query in Persian (e.g., *"یه هندزفری سیمی می‌خوام سریع بخرم"* or *"اسکوتر برقی مناسب چی بخرم؟"*). The system uses the **Jev System One Decision Model** (`POST /v1/systemone` via `typesafe-sdk` with OpenAI-compatible fallback) to evaluate the user's 15 preference parameters (`5 Global Base + 5 Cross-Category Persona + 5 Dynamic Category Spec` slots) and confidence levels. If core parameters have low effective confidence ($< 0.45$) and the user has not been asked yet (`clarification_count == 0`), [`FeatureClarificationCard.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/FeatureClarificationCard.tsx) renders **once** with quick chips and custom inputs. Thereafter, the assistant immediately returns ranked products from the 225,903-product catalogue with explainable match badges (`۹۴٪ تطابق`). Only if the user later expresses dissatisfaction (clicks 👎 `ThumbsDown` or `Jev` `user_dissatisfied.noul >= 0.70`) does the assistant ask a targeted second clarification round.

**Why this priority**: Directly powers **Step 1 (Need Discovery)**, **75 pts Product**, **75 pts UX Beyond Chat**, and **50 pts Intelligence**.

**Independent Test**: Send both a specific urgent query (*"سریع‌ترین شارژر سامسونگ نزدیک ولیعصر"*) and a vague query (*"گوشی موبایل می‌خوام"*). Verify the specific query skips clarification and prioritizes proximity (`w_dist`), while the vague query triggers `FeatureClarificationCard` once, updates the user's 15-slot profile in DB, and returns top matching products from `products.csv` + `offers.csv`.

**Acceptance Scenarios**:
1. **Given** a new shopping mission with vague intent ($\text{mean}(\text{EffConf}) < 0.45$ and `clarification_count == 0`), **When** the user submits the prompt, **Then** the UI hides the bottom chat input and displays `FeatureClarificationCard` with numbered questions, impact badges, chips, and custom inputs.
2. **Given** `clarification_count == 1` (user already answered or skipped), **When** the user sends follow-up messages, **Then** the assistant MUST NOT show another clarification card unless `ThumbsDown` is clicked or `user_dissatisfied.noul >= 0.70` (capped at `clarification_count == 2`).
3. **Given** a user profile stored in PostgreSQL (`user_profiles`) and cached in Redis with unconstrained weights $w_k^{\text{user}} \in [0, 1]$, **When** a new prompt arrives, **Then** the engine applies Confidence-Gated Fusion $\tilde{w}_k = \alpha_k \hat{w}_k^{\text{session}} + (1 - \alpha_k) w_k^{\text{user}}$, deduplicates new dynamic spec features via `pgvector` Embedding cosine similarity ($> 0.80$) + `Jev` `Noul` ($0.65\text{–}0.80$), and L1-normalizes active weights ($\sum_{k=1}^{15} \hat{w}_k = 1$) at query time.

---

### User Story 2 - Geo-Store Discovery, Interactive Dark Map & Multi-Criteria Store Ranking (Priority: P1) 🎯 MVP

Once candidate products are identified or selected, the user views physical Tehran stores that have verified offers in `offers.csv` (`331,506` offers across `6,476` shops). In [`ChatView.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/ChatView.tsx) (collapsible drawer) and [`StoresView.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/StoresView.tsx), stores are ranked using the 15-parameter utility function including the **Dealbreaker Hurdle Multiplier $\Phi(i)$**, **Net Value-of-Travel Coupling**, and **Pareto-Front Top-3 Diversity** (#1 Best Overall Match, #2 Closest Open Store, #3 Lowest Price / Best Installment). `StoresView` displays an interactive open-source **Leaflet / MapLibre dark-mode RTL map** with price pins alongside the ranked store cards, neighborhood selector (`userLocation`), and instant sidebar filters (`فقط مغازه‌های باز`, `پذیرنده ترب‌پی حضوری`, `خرید اقساطی / اسنپ‌پی`).

**Why this priority**: Covers **Step 2 (Store Location)** and **Step 3 (Smart Store Comparison)** plus **20 pts Dataset Mastery** (`offers.csv` vs. `shops.category_names` separation).

**Independent Test**: Select a recommended product in `ChatView` or switch to the `فروشگاه‌ها` (`stores`) tab, change `userLocation` (e.g., from `میدان ولیعصر` to `سعادت‌آباد`), toggle `پذیرنده ترب‌پی حضوری`, and verify the store list and Leaflet map pins re-rank in $<200\text{ ms}$ with accurate Haversine distances and Persian explainability badges.

**Acceptance Scenarios**:
1. **Given** a selected `product_id`, **When** querying physical stores, **Then** only shops with an explicit row in `offers.csv` for that `product_id` are returned as primary stocked stores (`shops.category_names` alone is never treated as product stock).
2. **Given** a user with a strict dealbreaker (`strict_installment` or `strict_open_now` detected via `Jev` `Noul >= 0.70` or Sidebar checkbox), **When** ranking offers, **Then** non-compliant offers receive hurdle multiplier $\Phi(i) = 0.15$ (or are filtered out when checkbox is active).
3. **Given** expanded store details in `StoresView`, **When** viewing a shop located inside a mall (e.g., `پاساژ علاءالدین 2، طبقه 6، واحد 622`), **Then** the card displays extracted indoor wayfinding badges (`پاساژ`, `طبقه`, `واحد`), `last_price_changed_at` relative freshness, `warranty`, and `payment_options` providers (`ترب‌پی`, `اسنپ‌پی`, `دیجی پی`, `تارا`, `ازکی‌وام`).

---

### User Story 3 - Dynamic Model Battle & Technical Spec Comparison Matrix (Priority: P2)

When comparing candidate models in the inline battle table ([`ChatView.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/ChatView.tsx)) or the dedicated `نبرد و مقایسه مدل‌ها` tab ([`ComparisonView.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/ComparisonView.tsx)), the UI dynamically populates side-by-side product cards and the expandable technical specification matrix from the actual JSON `specs` column of `products.csv` for *any* product category (replacing the hardcoded scooter-only logic in `UI_Template`).

**Why this priority**: Completes the "Beyond Chat" comparison flow across all 225,903 products in `products.csv`.

**Independent Test**: Search for two different categories (e.g., `دوربین مدار بسته` and `گوشی موبایل`), open the `compare` tab (`Swords` icon), and verify the top 3 key decision specs and the full expandable spec table dynamically render the category's real `products.specs` keys and Tehran floor prices.

**Acceptance Scenarios**:
1. **Given** any list of `recommendedProducts` from `products.csv`, **When** the user opens `ComparisonView`, **Then** the 3-card header and expandable comparison table display the real parsed `specs` keys, `minPrice` in Tehran, and `storeCount` from `offers.csv`.

---

### User Story 4 - Live Shopping Companion, Store Contact Transparency & 1-Tap Fallback (Priority: P2)

When the user clicks `تماس با فروشگاه` or `همراهی خرید` on any store offer:
- [`StoreContactModal.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/StoreContactModal.tsx) displays the shop's phone (`contacts`), `رسمی` badge + clickable `instagram` / `website_url` (for the 112 real shops), working hours (`weekly_hours`), `last_price_changed_at` freshness badge, and pre-visit inquiry tips.
- [`ShoppingCompanionModal.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/ShoppingCompanionModal.tsx) guides the user through the 4-step physical visit (`۱. مسیریابی` with Neshan/Balad/Google Maps links + indoor mall `طبقه/واحد` guide $\rightarrow$ `۲. تست در مغازه` checklist $\rightarrow$ `۳. پرداخت و فاکتور` $\rightarrow$ `۴. پایان خرید`), minimizes into a persistent floating bottom bar, and provides 1-tap rescue actions (`مغازه بسته بود؟ فروشگاه جایگزین` and `گزارش مغایرت قیمت`) that query the backend for the nearest open alternative store stocking the same product.

**Why this priority**: Directly addresses **Step 4** and Pain Points #2 (stale prices), #3 (closed shop fallback), and #4 (indoor mall confusion).

**Independent Test**: Click `همراهی خرید` on a store in Charsou, verify Step 1 shows Neshan/Balad/Google Maps deep links and indoor `طبقه/واحد`, click `مغازه بسته بود؟`, and verify it returns a real nearby alternative shop from `offers.csv` (replacing the hardcoded `فروشگاه تکنولند جمهوری` placeholder) and allows 1-tap switching.

**Acceptance Scenarios**:
1. **Given** an active store offer in `StoresView` or `ShoppingCompanionModal`, **When** the user clicks `مغازه بسته بود؟ فروشگاه جایگزین`, **Then** the system queries `offers.csv` $\bowtie$ `shops.csv` for the closest open store stocking the same `product_id` (or highest-utility alternative within radius) and lets the user switch active companion target in 1 tap.
2. **Given** user interaction with `ThumbsUp`/`ThumbsDown`, Sidebar filters, or `گزارش مغایرت قیمت`, **When** the event fires, **Then** `POST /api/feedback` updates the user's 15-parameter weights in PostgreSQL (`user_profiles`) and invalidates/updates the Redis session cache.

---

### User Story 5 - Final-Phase Liara Containerized Deployment & Demo Readiness (Priority: P3 — Final Phase Only)

In the **final phase** (after all local features, dataset indexing, RecSys, and UI flows are complete and verified), package the FastAPI + React/Vite build alongside PostgreSQL (`pgvector`) + Redis into a clean Docker/Liara setup (`Dockerfile` + `docker-compose.yml` + `liara.json`) for deployment on Liara, accompanied by a 5-minute Demo Video script.

**Why this priority**: Worth **40 pts Deploy** + mandatory video deliverable, scheduled strictly as the **last phase** per user direction.

**Independent Test**: Build and run the production container locally (`docker build` / `docker run`), verify `<500ms` search/ranking response and full RTL UI rendering, then deploy to Liara.

---

### Edge Cases

- **Literal `"null"` strings in CSVs**: Columns like `model`, `instagram`, `website_url`, `supports_fast_delivery`, `weekly_hours`, and `warranty` contain the literal string `"null"` (and `payment_options` may be `"[]"`). The ingestion pipeline MUST normalize `"null"` $\rightarrow$ SQL `NULL` and display `"نامشخص / ثبت نشده"` in UI badges without crashing.
- **Product with 0 Open Stores at Current Time**: If `filterOpenOnly` is active or the user asks at midnight when all stores are closed, return the top stores sorted by their **next opening shift** in `weekly_hours` with a clear `"در حال حاضر بسته — بازگشایی فردا ساعت ..."` badge rather than an empty screen.
- **No `TYPESAFE_API_KEY` Configured**: The Dual-Mode `Jev` client automatically falls back to the OpenAI-compatible System-One emulator (`.env`: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`) returning identical `ScoreAnswer`, `NoulAnswer`, and `ChoiceAnswer` objects with exact MAD/mode confidence math.

---

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST ingest `dataset/shops.csv` (6,476 rows), `dataset/products.csv` (225,903 rows), and `dataset/offers.csv` (331,506 rows) into an indexed **PostgreSQL + `pgvector`** database (with **Redis** caching for active sessions and hot queries) while normalizing literal `"null"` strings to `NULL`.
- **FR-002**: System MUST strictly separate `offers.csv` (verified product-in-store offers) from `shops.category_names` (general business categories) in all product-store queries.
- **FR-003**: System MUST parse `shops.address` to extract indoor mall micro-location fields (`mall_name`, `mall_floor`, `mall_unit`, `mall_note`) for shops inside malls/passages.
- **FR-004**: System MUST parse `shops.payment_options` JSON to identify in-person credit and installment providers (`ترب‌پی`, `اسنپ‌پی`, `دیجی پی`, `تارا`, `ازکی‌وام`) and `channel` (`in_person` vs. `unknown`).
- **FR-005**: System MUST flag the **112 real shops** (`instagram != NULL OR website_url != NULL`) with `is_real_shop = true` (`فروشگاه رسمی` badge) and expose their real social/web links in `StoreContactModal`.
- **FR-006**: System MUST implement the **15-Parameter Adaptive RecSys** with `5 Global Base Slots` + `5 Cross-Category Persona Slots` + `5 Dynamic Category Spec Slots` persisted per user in the database with unconstrained weights $w_k^{\text{user}} \in [0, 1]$.
- **FR-007**: System MUST evaluate prompt intent and feature fitness in parallel using `Jev` (`POST /v1/systemone` via `typesafe-sdk` with OpenAI-compatible fallback), returning calibrated `score`, `noul`, `choice`, `probabilities`, and `confidence`.
- **FR-008**: System MUST blend session weights and stored user weights via Confidence-Gated Fusion $\tilde{w}_k(u, q) = \alpha_k(q)\hat{w}_k^{\text{session}}(q) + (1 - \alpha_k(q))w_k^{\text{user}}(u)$ and L1-normalize active weights ($\sum_{k=1}^{15} \hat{w}_k = 1$) at query-time ranking.
- **FR-009**: System MUST deduplicate newly extracted dynamic spec features ($k \in \{11..15\}$) using Stage-1 Embedding cosine similarity ($> 0.80$) + Stage-2 parallel `Jev` `Noul` equivalence check ($0.65\text{–}0.80$), evicting the lowest-fit slot when full.
- **FR-010**: System MUST apply the Dealbreaker Hurdle Multiplier $\Phi(i) \in \{1.0, 0.15\}$, Net Value-of-Travel Coupling, and Pareto-Front Top-3 diversity when ranking store offers.
- **FR-011**: System MUST enforce the Anti-Fatigue Clarification Policy: trigger `FeatureClarificationCard.tsx` at most once on Turn 1 when $\text{mean}(\text{EffConf}_k) < 0.45$, and only re-trigger a second time if the user clicks `ThumbsDown` or `user_dissatisfied.noul >= 0.70`.
- **FR-012**: Frontend MUST preserve the theme (`#0c0c10` / `#e9325a`), custom SVG animations (`TorobLogo`, `SearchingPapersAnimation`), and component layout of [`UI_Template/`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template), while adding an open-source Leaflet/MapLibre dark-mode RTL map in `StoresView`, dynamic spec comparison in `ComparisonView`, indoor mall floor/unit badges, and dynamic backup store lookup.

### Key Entities

- **`Product`**: Catalog item from `products.csv` (`product_id`, `persian_title`, `brand_name`, `category_name`, `model`, `image_urls`, `specs`, computed `min_price_toman`, `max_price_toman`, `offer_count`).
- **`Shop`**: Physical Tehran store from `shops.csv` (`shop_id`, `name`, `is_real_shop`, `address`, `mall_name`, `mall_floor`, `mall_unit`, `location_label`, `lat`, `lon`, `category_names`, `contacts`, `instagram`, `website_url`, `payment_options`, `supports_fast_delivery`, `weekly_hours`).
- **`Offer`**: Product-in-store record from `offers.csv` (`offer_id`, `product_id`, `shop_id`, `price_toman`, `last_price_changed_at`, `seller_title`, `description`, `warranty`).
- **`UserProfile`**: Persistent 15-parameter preference state (`user_id`, `base_weights[5]`, `base_confidences[5]`, `persona_weights[5]`, `persona_confidences[5]`, `dynamic_slots[5]` with `{name, spec_key, weight, confidence, embedding, updated_at}`, `clarification_count`).

---

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001 (Search & RecSys Latency)**: PostgreSQL (`pgvector` + `pg_trgm`) + Redis candidate retrieval and `Jev` 15-parameter scoring completes in $< 600\text{ ms}$ p95 across 225,903 products and 331,506 offers.
- **SC-002 (Dataset Accuracy)**: $100\%$ of stores shown as stocking a product have a verified join row in `offers.csv`; $100\%$ of the 112 real shops display the `رسمی` badge and valid Instagram/Website links.
- **SC-003 (Situational vs. Persona Adaptation)**: In automated self-checks, an urgent low-price query (*"سریع‌ترین هندزفری سیمی"*) assigns $\hat{w}_{\text{dist}} > 2 \times \hat{w}_{\text{price}}$, whereas a high-value price-sensitive query by the same user (*"ارزان‌ترین آیفون"*) assigns $\hat{w}_{\text{price}} > 2 \times \hat{w}_{\text{dist}}$.
- **SC-004 (Anti-Fatigue Clarification Compliance)**: `FeatureClarificationCard` never triggers more than once per shopping mission unless an explicit `ThumbsDown` or dissatisfaction signal (`noul >= 0.70`) occurs.
- **SC-005 (End-to-End Beyond-Chat UX)**: A user can complete all 4 shopping stages (Product Selection $\rightarrow$ Map/Store Discovery $\rightarrow$ Multi-Criteria Comparison $\rightarrow$ Contact / Companion / 1-Tap Backup Store) purely via interactive UI cards, chips, and buttons without typing follow-up text.
