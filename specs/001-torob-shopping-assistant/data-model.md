# Data Model: Torob Smart In-Person Shopping Assistant (`001-torob-shopping-assistant`)

**Date**: 2026-11-06  
**Storage Engine**: **PostgreSQL 16+ with `pgvector` (`vector`) and `pg_trgm` extensions** + **Redis 7+** (session state, anti-fatigue counters & hot query/profile cache).  
**Guardrails**: Enforced by [`torob-dataset-guard`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/.agents/skills/torob-dataset-guard/SKILL.md).

---

## 0. Required PostgreSQL Extensions

```sql
CREATE EXTENSION IF NOT EXISTS vector;   -- pgvector for semantic product search & Stage-1 slot deduplication
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- Trigram GIN indexing for Persian title search
```

---

## 1. Core Dataset Entities in PostgreSQL (Ingested from `dataset/*.csv`)

### 1.1 `shops` (`6,476` rows from `dataset/shops.csv`)
Represents physical retail storefronts across Tehran.

| Column | PostgreSQL Type | Source / Null Handling | Validation & Indexing Rules |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER PRIMARY KEY` | `shops.id` | Unique store identifier (`746`..`89543`). |
| `name` | `TEXT NOT NULL` | `shops.name` | Persian shop name; indexed via `GIN (name gin_trgm_ops)`. |
| `latitude` | `DOUBLE PRECISION NOT NULL` | `shops.latitude` | Validated in Tehran bounding box ($[35.50, 35.85]$); composite index `(latitude, longitude)`. |
| `longitude` | `DOUBLE PRECISION NOT NULL` | `shops.longitude` | Validated in Tehran bounding box ($[51.10, 51.65]$). |
| `address` | `TEXT` | `shops.address` (`"null"` $\rightarrow$ `NULL`) | Full Persian street/mall address. |
| `mall_name` | `TEXT` | Extracted at ingest | Regex over `address`: `(پاساژ\|مجتمع تجاری\|مجتمع\|مرکز خرید\|بازار)\s+([^،\n]+)` (3,872 matches across `پاساژ` 3,179, `مجتمع` 467, `بازار` 186, `مرکز خرید` 40). |
| `floor_label` | `TEXT` | Extracted at ingest | Regex over `address`: `طبقه\s+([^،\n]+)` (4,224 matches; e.g., `همکف`, `منفی ۱`, `دوم`). |
| `unit_label` | `TEXT` | Extracted at ingest | Regex over `address`: `(واحد\|پلاک)\s+([0-9۰-۹A-Za-z/-]+)` (7,471 matches). |
| `phones_json` | `JSONB` | `shops.phones` | Array of phone numbers (e.g., `["02166701234", "0912..."]`). |
| `primary_phone` | `TEXT` | Derived (`phones_json->>0`) | First callable phone number for `StoreContactModal.tsx`. |
| `score` | `DOUBLE PRECISION` | `shops.score` (`1.0`..`5.0`) | Store rating; normalized to $x_{\text{score}} = (\text{score} - 1.0)/4.0 \in [0, 1]$. |
| `votes_count` | `INTEGER` | `shops.votes_count` (`0`..`193`) | Bayesian confidence weight for store rating: $v / (v + 10)$. |
| `has_delivery` | `BOOLEAN` | `shops.has_delivery` | True in 6,418 / 6,476 shops. |
| `payment_options_json` | `JSONB` | `shops.payment_options` | `GIN`-indexed JSONB array of `{"provider_name": "ترب‌پی"\|"اسنپ‌پی"\|"دیجی پی"\|"تارا"\|"ازکی‌وام", "channel": "in_person"\|"unknown", "min_price_toman": int\|null, "max_price_toman": int\|null, "category_names": [...]}`. |
| `has_in_person_installment` | `BOOLEAN` | Derived at ingest | `TRUE` if any entry in `payment_options_json` has `channel = 'in_person'`. |
| `installment_providers` | `TEXT[]` | Derived at ingest | Distinct `provider_name` values where `channel = 'in_person'`. |
| `weekly_hours_json` | `JSONB NOT NULL` | `shops.weekly_hours` (100% non-null) | Keyed by `["sat","sun","mon","tue","wed","thu","fri"]` $\rightarrow$ `{"status": "declared"\|"closed"\|"unsupported", "shifts": [{"start_time": "HH:MM:SS", "end_time": "HH:MM:SS"}]}`. |
| `category_names_json` | `JSONB` | `shops.category_names` | General shop category list (`GIN`-indexed). **CRITICAL RULE**: Used ONLY when no product matches in `offers` (`is_category_fallback = true`). |
| `website_url` | `TEXT` | `shops.website_url` (`"null"` $\rightarrow$ `NULL`) | Non-null in 112 real Torob stores. |
| `instagram` | `TEXT` | `shops.instagram` (`"null"` $\rightarrow$ `NULL`) | Non-null in 112 real Torob stores. |
| `is_real_torob_shop` | `BOOLEAN` | Derived (`website_url IS NOT NULL OR instagram IS NOT NULL`) | Flags the 112 verified real-world shops (`تایید شده ترب`). |

---

### 1.2 `products` (`225,903` rows from `dataset/products.csv`)
Represents the canonical product catalog, structured technical specifications, and `pgvector` semantic embeddings.

| Column | PostgreSQL Type | Source / Null Handling | Validation & Indexing Rules |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER PRIMARY KEY` | `products.id` | Unique product identifier (`947010`..`122792219`). |
| `name` | `TEXT NOT NULL` | `products.name` | Persian + English model name. |
| `normalized_name` | `TEXT NOT NULL` | Derived at ingest | Persian character normalization (`ی`/`ک`, ZWNJ removal, Eastern-to-Western digits); indexed via `GIN (normalized_name gin_trgm_ops)`. |
| `category_id` | `INTEGER NOT NULL` | `products.category_id` | Category identifier (`872` distinct categories); B-tree indexed. |
| `category_name` | `TEXT NOT NULL` | `products.category_name` | Persian category title (e.g., `گوشی موبایل`, `کنسول بازی`, `هدفون، هدست و هندزفری`). |
| `brand_id` | `INTEGER` | `products.brand_id` (`"null"` $\rightarrow$ `NULL`) | Null in 147,534 rows; non-null in 78,369 rows. |
| `brand_name` | `TEXT` | `products.brand_name` (`"null"` $\rightarrow$ `NULL`) | Brand name when available (e.g., `سامسونگ (Samsung)`). |
| `specs_json` | `JSONB` | `products.specs` (`"{}"` or `"null"` $\rightarrow$ `'{}'::jsonb`) | `GIN`-indexed variable JSONB key-value map per category (e.g., `حافظه داخلی`, `رم`, `ظرفیت باتری`). |
| `embedding` | `vector(1536)` | `pgvector` column | HNSW-indexed (`USING hnsw (embedding vector_cosine_ops)`) for hybrid semantic + lexical product retrieval. |
| `min_price_toman` | `BIGINT` | Pre-aggregated from `offers` | Minimum active offer price for fast catalog filtering. |
| `offer_count` | `INTEGER` | Pre-aggregated from `offers` | Count of physical stores stocking this exact product. |

---

### 1.3 `offers` (`331,506` rows from `dataset/offers.csv`)
The authoritative join table linking physical `shops` to actual stocked `products` with live pricing.

| Column | PostgreSQL Type | Source / Null Handling | Validation & Indexing Rules |
| :--- | :--- | :--- | :--- |
| `id` | `INTEGER PRIMARY KEY` | `offers.id` | Unique offer identifier (`1000039`..`225013485`). |
| `product_id` | `INTEGER NOT NULL REFERENCES products(id)` | `offers.product_id` | B-tree composite index `idx_offers_product_price (product_id, price_toman)`. |
| `shop_id` | `INTEGER NOT NULL REFERENCES shops(id)` | `offers.shop_id` | B-tree index `idx_offers_shop_id (shop_id)`. |
| `price_toman` | `BIGINT NOT NULL` | `offers.price` | Price in **Tomans** (`1,000` to `25,112,200,000`). Formatted in UI with Persian digits + `تومان`. |
| `warranty_raw` | `TEXT` | `offers.warranty` (`"null"` $\rightarrow$ `NULL`) | Non-null in 58,943 rows; literal `"null"` in 272,563 rows. |
| `has_official_warranty` | `BOOLEAN` | Derived at ingest | `TRUE` if `warranty_raw` is valid JSON with `provider IS NOT NULL` or `period_months > 0` (and not `"بدون گارانتی"`). |
| `warranty_provider` | `TEXT` | Derived from `warranty_raw` JSON | e.g., `شرکتی`, `داریا همراه`, `۱۸ ماهه`. |
| `warranty_months` | `INTEGER` | Derived from `warranty_raw` JSON | `period_months` integer when available. |
| `last_price_changed_at` | `TIMESTAMPTZ` | `offers.last_price_changed_at` (`"null"` $\rightarrow$ `NULL`) | Non-null in 330,737 rows (ISO-8601 UTC). Used to compute price freshness $x_{\text{freshness}} = \exp(-\Delta t_{\text{days}} / 14)$. |

---

## 2. Adaptive RecSys Entities (PostgreSQL + `pgvector` + Redis)

### 2.1 `user_profiles` & `user_dynamic_slots` (PostgreSQL + `pgvector` Persistent Store)
Stores per-user preference vectors across sessions. Weights are stored **unconstrained in $[0.0, 1.0]$** in PostgreSQL (Layer 1) to prevent dilution when slots are updated, and **L1-normalized at query time** ($\sum_{k=1}^{15} \hat{w}_k = 1$, Layer 2). Hot profiles are cached in **Redis** under `torob:profile:{user_id}` (`TTL = 24h`) with write-through to PostgreSQL.

| Table / Column | PostgreSQL Type | Description & Constraints |
| :--- | :--- | :--- |
| `user_profiles.user_id` | `TEXT PRIMARY KEY` | Client session/device UUID (`X-User-Id` header or payload). |
| `user_profiles.base_weights_json` | `JSONB NOT NULL` | **Slots 1–5 (Global Base, always present)**:<br>`w_distance` ($k=1$, default `0.50`), `w_price` ($k=2$, default `0.60`), `w_score` ($k=3$, default `0.40`), `w_open_now` ($k=4$, default `0.50`), `w_freshness` ($k=5$, default `0.40`). Each $\in [0.0, 1.0]$. |
| `user_profiles.persona_weights_json` | `JSONB NOT NULL` | **Slots 6–10 (Cross-Category Persona)**:<br>`w_installment` ($k=6$), `w_warranty` ($k=7$), `w_mall_cluster` ($k=8$), `w_verified_shop` ($k=9$), `w_delivery_backup` ($k=10$). Each $\in [0.0, 1.0]$. |
| `user_profiles.interaction_count` | `INTEGER DEFAULT 0` | Total shopping turns completed by this user. |
| `user_profiles.updated_at` | `TIMESTAMPTZ` | Timestamp of last profile EMA update. |
| `user_dynamic_slots.user_id` | `TEXT REFERENCES user_profiles(user_id)` | Composite PK `(user_id, slot_id)` where `slot_id BETWEEN 11 AND 15` (**Slots 11–15**). |
| `user_dynamic_slots.feature_key` | `TEXT NOT NULL` | Canonical feature identifier (e.g., `spec_anc_mic`, `spec_battery_life`). |
| `user_dynamic_slots.label_fa` | `TEXT NOT NULL` | Persian UI label for the slider/chip. |
| `user_dynamic_slots.category_id` | `INTEGER` | Associated category ID. |
| `user_dynamic_slots.weight` | `DOUBLE PRECISION NOT NULL` | Unconstrained weight $\in [0.0, 1.0]$. |
| `user_dynamic_slots.confidence` | `DOUBLE PRECISION NOT NULL` | Latest `Jev` confidence $\in [0.0, 1.0]$. |
| `user_dynamic_slots.embedding` | `vector(1536) NOT NULL` | **`pgvector` embedding** of the feature label/concept for native `<=>` cosine deduplication. |
| `user_dynamic_slots.session_hits` | `INTEGER DEFAULT 1` | Usage count for decayed-utility LRU eviction. |

**Slot Replacement Invariant (Slots 11–15 via `pgvector` + `Jev` `Noul`)**:
When a new candidate feature $f_{\text{new}}$ with embedding $\mathbf{e}_{\text{new}}$ is extracted:
1. **Stage-1 `pgvector` Cosine Gate**: Execute `SELECT slot_id, 1 - (embedding <=> $1::vector) AS cos_sim FROM user_dynamic_slots WHERE user_id = $2 ORDER BY embedding <=> $1::vector LIMIT 1;`. If `cos_sim > 0.80`, merge directly into `slot_id`.
2. **Stage-2 `Jev` `Noul` Gate**: If `cos_sim BETWEEN 0.65 AND 0.80`, query `Jev` `same_feature_concept.noul`. If $\ge 0.65$, merge into `slot_id`.
3. **Eviction**: Otherwise, if all 5 dynamic slots ($11..15$) are occupied, evict $\arg\min_{k \in \{11..15\}} \left(w_k^{\text{user}} \cdot \exp(-\lambda_{\text{decay}} \cdot \Delta\text{sessions}_k)\right)$ and `UPSERT` $f_{\text{new}}$ so total parameters strictly equal $15$.

---

### 2.2 `shopping_sessions` (Redis Primary State + PostgreSQL Audit Backup)
Active conversation sessions and anti-fatigue counters live in **Redis** under key `torob:session:{session_id}` (`TTL = 6h`) for `< 2 ms` read/write per turn, with asynchronous snapshot persistence to PostgreSQL `shopping_sessions`.

| Field | Type (Redis JSON / PostgreSQL) | Description & Constraints |
| :--- | :--- | :--- |
| `session_id` | `TEXT PRIMARY KEY` | Unique conversation thread ID. |
| `user_id` | `TEXT NOT NULL` | Foreign key to `user_profiles.user_id`. |
| `user_lat`, `user_lng` | `DOUBLE PRECISION` | User coordinates in Tehran (defaults to `35.7219, 51.3347` or browser GPS). |
| `active_category_id` | `INTEGER` | Detected target product category ID. |
| `effective_weights_json` | `JSONB NOT NULL` | Current L1-normalized 15-weight vector $\hat{\mathbf{w}} \in \Delta^{14}$ ($\sum_{k=1}^{15} \hat{w}_k = 1.0$) and per-slot `confidence`. |
| `hard_constraints_json` | `JSONB NOT NULL` | Dealbreaker flags (`require_open_now`, `require_installment`, `require_warranty`) driving $\Phi(i) \in \{1.0, 0.15\}$. |
| `clarification_count` | `INTEGER DEFAULT 0` | Number of times `FeatureClarificationCard` has been shown in this mission (`0`, `1`, or max `2`). |
| `dissatisfaction_triggered` | `BOOLEAN DEFAULT FALSE` | Set to `TRUE` only if user clicks 👎 (`ThumbsDown`) or `Jev` `user_dissatisfied.noul >= 0.70`, unlocking at most one follow-up clarification (`clarification_count: 1 -> 2`). |
| `messages_json` | `JSONB NOT NULL` | Ordered turn history (`role`, `text`, `ui_widget_payload`, `timestamp`). |

**Redis Key Namespace Summary**:
- `torob:session:{session_id}` $\rightarrow$ Active `shopping_sessions` state + `clarification_count` anti-fatigue gate (`TTL = 6h`)
- `torob:profile:{user_id}` $\rightarrow$ Read-through / write-through cache of `user_profiles` + 15-slot vector (`TTL = 24h`)
- `torob:qcache:{hash}` $\rightarrow$ Cached candidate offers for repeated product/geo queries (`TTL = 5m`)

---

## 3. Computed Ranking & Response View Models

### 3.1 `ScoredOfferCandidate`
Produced at query time by joining `offers` $\bowtie$ `products` $\bowtie$ `shops` in PostgreSQL (`pgvector` + `pg_trgm`) and evaluating the 15-parameter utility engine:

$$U(u, q, i) = \Phi(i) \cdot \left[ \sum_{k=1}^{15} \hat{w}_k(u, q) \cdot x_k(i, q) - \lambda_{\text{travel}}(u, q) \cdot \frac{\text{TravelCost}_{\text{Toman}}(u, i)}{\text{Price}_{\text{Toman}}(q)} \right]$$

Each top-ranked candidate serialized to the frontend includes:
- **Identity**: `offer_id`, `product_id`, `product_name`, `shop_id`, `shop_name`
- **Pricing & Freshness**: `price_toman`, `last_price_changed_at`, `freshness_label_fa` (e.g., `بروزرسانی ۲ ساعت پیش`), `freshness_hours`
- **Geo & Travel**: `distance_km`, `driving_minutes`, `walking_minutes`, `latitude`, `longitude`, `address`
- **Indoor Mall Micro-Navigation**: `mall_name` (`پاساژ علاءالدین`), `floor_label` (`طبقه ۲`), `unit_label` (`واحد ۲۱۴`)
- **Trust & Payment**: `shop_score`, `votes_count`, `has_official_warranty`, `warranty_provider`, `has_in_person_installment`, `installment_providers`, `is_real_torob_shop`, `is_open_now`, `today_hours_fa`
- **Explainable RecSys Attribution**: `utility_score` ($\in [0, 100]$), `pareto_role` (`"best_overall"` | `"closest_open"` | `"lowest_price"`), `why_this_shop_fa` (top-2 contributing weighted parameters $c_k = \hat{w}_k \cdot x_k$), and `is_category_fallback` (`false` for `offers.csv` stock match; `true` for general shop category fallback).
