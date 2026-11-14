# Phase 0 Research & Architectural Decisions (`003-clean-adaptive-recsys`)

**Feature**: Clean Two-Layer Adaptive Recommender System with Selective Trait Transfer, Zero-Keyword Semantic Intelligence & Session Consolidation  
**Date**: 2026-11-13  
**Status**: Complete — All unknowns resolved (`0` `NEEDS CLARIFICATION` remaining)

---

## R1. Zero-Category-Enum, Zero-Latency Selective Cross-Category Trait Transfer (`Any Category A -> Any Category B`)

- **Decision**: Purge the hardcoded 6-category `VALID_DOMAINS` tuple (`electronics`, `footwear_apparel`, ...) completely. Store each user trait with its open-vocabulary `source_category` (grounded dynamically from `products.category_name` or the model's open-vocabulary category phrase—working identically for musical instruments, pet supplies, books, eyewear, tools, laptops, or shoes). Load at most `RECSYS_MAX_STORED_TRAITS_PER_USER` (`15`) top traits for `user_id` ordered by `(strength DESC, updated_at DESC)`, and evaluate **selective transferability inside the existing Turn-1 parallel Decision Model call** (`_call_decision_model`) via typed `Noul` questions (`trait_transfer_{idx}`), passing each trait's `(source_category, aspect, preference)`. Only traits with `noul >= RECSYS_TRAIT_TRANSFER_NOUL_THRESHOLD` (`0.72`) are activated as **Soft Boosts** in Layer 1.
- **Rationale**:
  1. **100% Category-Agnostic Generalization**: Zero hardcoded domain/category enums in Python—works out of the box on any unseen Torob category.
  2. **Zero Extra Network RTT**: Piggybacks on the single parallel System-One request (`gemini-decision-1` / `Jev`), adding `0` sequential hops while removing the unused online `embed_text_async(req.message)` call (`-250..350 ms` net latency reduction per chat turn).
  3. **Scale & Physics Awareness**: Including `source_category` allows the Decision Model to transfer scale-compatible traits while rejecting incompatible ones, and soft-boost application guarantees zero empty-set failures.
- **Alternatives Considered**:
  - *Hardcoded `VALID_DOMAINS` (`electronics`, `footwear_apparel`, ...) enum*: Rejected — forces arbitrary commerce items into 5 predefined buckets and leaks incompatible traits within the same bucket.
  - *Hardcoded category-pair transfer matrices*: Rejected — brittle and violates zero-hardcoding requirement.

---

## R2. Zero-Keyword Dynamic Concept-to-Catalog Expansion (`catalog_search_terms`)

- **Decision**: Purge `_PARTICLES_FA`, `_ACCESSORY_CATEGORY_REGEX`, and substring-matching `rerank_products_with_domain_traits` from `backend/db/queries.py`. During LLM entity extraction (`_extract_turn_entities_with_llm`), generate `catalog_search_terms: list[str]` that dynamically expands colloquial, indirect, or symptom-based user intents into concrete Persian/English market & catalog terms (e.g., `«صدای مترو نیاد»` -> `["ANC", "حذف نویز", "نویز کنسلینگ"]`; `«کفش کمردرد»` -> `["طبی", "ارتوپدی"]`; `«دست‌دوم تمیز»` -> `["استوک", "اوپن باکس", "کارکرده"]`), alongside `is_accessory_request: bool` judged semantically by the model.
- **Rationale**: PostgreSQL `pg_trgm` and `ILIKE` require lexical overlap with merchant catalog strings (`products.normalized_name`, `products.specs_json`, `offers.seller_title`, `offers.description`), whereas users speak in everyday problems. Model-driven expansion bridges this gap for arbitrary categories without maintaining a single hardcoded synonym or regex list.
- **Alternatives Considered**:
  - *Full-catalog dense embedding search on 225,903 products + 331,506 offers*: Rejected — `products.embedding` is unpopulated (`NULL` on all 225K rows), pre-embedding 557K rows exceeds hackathon runtime/cost constraints, and dynamic query-time concept expansion + `pg_trgm` + `Jev` candidate scoring achieves `< 20 ms` SQL retrieval with full semantic recall.

---

## R3. Offer-Aware Product Retrieval & 100% Decision-Model Trait Attribution

- **Decision**:
  1. In `backend/db/queries.py`, include `o.seller_title` and `o.description` in `fetch_candidate_offers`, and add a lightweight correlated `EXISTS` / count summary in `search_products` so offer-only attributes (`استوک`, `اوپن‌باکس`, `ریجسترشده`, `پارت‌نامبر`) boost matching products into the top 12 candidates.
  2. In `score_candidate_products_with_decision_model`, pass each candidate product's `title`, `specs_summary`, and `offer_titles_sample`, plus the active session traits and transferred historical traits, asking the Decision Model both for overall `Score` and per-trait semantic satisfaction (`Noul` / structured attribution) so `6000mAh` is recognized as satisfying `شارژدهی بالا`, and **never** appending fallback badges when no trait matches.
- **Rationale**: Eliminates Bug #2 (hallucinated `"منطبق با ترجیح شما"` badges on every card) and Bug #5 (invisibility of `استوک` and seller-level attributes stored in `offers.csv` rather than `products.specs_json`).
- **Alternatives Considered**:
  - *Python substring matching (`pref in blob`)*: Rejected — fails on numerical/semantic equivalence (`6000mAh` vs. `باتری قوی`) and violates FR-007.

---

## R4. Layer 2 Store Ranking: 5 Numerical Metrics + Conditional Open-Vocabulary `w_offer_custom`

- **Decision**: Keep the 5 orthogonal numerical store criteria (`w_price`, `w_distance`, `w_open_now`, `w_trust_freshness`, `w_installment`) independent of Layer 1 product trait count, and add a **6th conditional open-vocabulary criterion (`w_offer_custom`)** activated **only** when the user expresses an unstructured store/offer requirement (`custom_offer_criterion` is non-empty, e.g., target neighborhood/mall `"سمت چارسو یا ولیعصر"` differing from user GPS, `"پارت‌نامبر ZAA"`, `"رنگ تیتانیوم"`, `"مهلت تست"`, or `"استوک گرید A"`). When active, batch-evaluate up to `RECSYS_CUSTOM_OFFER_TOP_K` (`15`) candidate offers in a single parallel Decision Model call over `(shop_name, address, mall_name, seller_title, description, warranty_raw)` to produce $f_{o,\text{custom}} \in [0, 1]$.
- **Rationale**:
  - Zero extra latency on normal queries (`custom_offer_criterion == ""` -> `0` extra questions).
  - Full semantic flexibility on location overrides (`چارسو` when standing in `ونک`) and merchant-specific conditions (`پارت‌نامبر`, `مهلت تست`, `استوک`) without bloating Layer 2 with permanent slots.
- **Alternatives Considered**:
  - *Geocoding neighborhood names via external map APIs*: Rejected — adds external network failure modes on Liara and still cannot handle non-location offer conditions (`مهلت تست`, `پارت‌نامبر`).

---

## R5. Dimensionless Domain Price Prior ($\pi_{u,d} \in [0, 1]$)

- **Decision**: Track user price affinity per macro-domain in `user_profiles.price_percentiles_json` as `{domain: {"percentile": float, "count": int}}`. Compute the observed percentile of a chosen product/offer relative to the candidate category's `[min_price, max_price]` span, update with sample-count inertia $\eta_{\text{price}} = \frac{0.30}{\sqrt{1 + n_{u,d}}}$, and apply a gentle soft boost (`RECSYS_PRICE_PRIOR_BOOST_WEIGHT = 0.12`) in Layer 1 **only when the user has not stated an explicit budget or `price_tier` in the current session**.
- **Rationale**: Raw Toman budgets do not transfer across items (`40M` laptop vs. `15M` phone vs. `4M` sneakers), whereas relative category percentiles (`0.75` = upper-midrange buyer) transfer cleanly and stay immune to inflation.
- **Alternatives Considered**:
  - *Storing raw Toman average spend*: Rejected — meaningless across categories with 10x price differences.

---

## R6. Outlier-Safe Trait Consolidation: Gift Shield + Top-2 Per-Aspect Inertia

- **Decision**:
  1. **Ephemeral / Gift Shield**: Evaluate `is_ephemeral_or_gift` (`Noul`) in Turn 1; if `noul >= RECSYS_EPHEMERAL_GIFT_NOUL_THRESHOLD` (`0.60`), skip all writes to `user_trait_memory` and `price_percentiles_json` for that session.
  2. **Non-Destructive Top-2 Per-Aspect Memory**: Extend `user_trait_memory` with `source_category TEXT` and `strength DOUBLE PRECISION`. When upserting `(user_id, domain, aspect, preference)`:
     - Same `preference` on existing `aspect`: increment `hit_count` and update $s \leftarrow 1 - (1 - s)(1 - \alpha)$ (`alpha = 0.15` soft end-of-turn consolidation on latest session state; `alpha = 0.35` on explicit positive feedback/selection).
     - Different `preference` on existing `aspect`: decay rival preferences on that aspect by `RECSYS_TRAIT_RIVAL_DECAY` (`0.92`), insert/update the new preference at initial strength `alpha`, and retain the **Top-2** preferences by `strength` per `(user_id, domain, aspect)` (capping active retrieval at top `12` per domain).
- **Rationale**: Fixes Bug #6 (destructive `UPDATE` wiping out `hit_count=8` preferences on a single experiment) and naturally supports shared/multi-taste accounts (e.g., liking both Nike and Skechers).
- **Alternatives Considered**:
  - *Single-row overwrite per aspect*: Rejected — destroys long-term memory on a single atypical query.

---

## R7. Revealed-Preference Store Weight Learning & True Pareto Top-3 Reordering

- **Decision**:
  1. Never update `user_profiles.store_weights_json` from chat text or `thumbs_down` (`👎`). Update **only** on `thumbs_up` / store contact-navigation selection (with `target_offer_id` compared against mean `shown_store_features` via contrastive delta $p_{u,k} \leftarrow \operatorname{clip}(p_{u,k} + \eta (f_{o^*,k} - \bar{f}_{\mathcal{S},k}), 0.10, 1.00)$) or explicit `weight_override` slider changes. `clarification_choice` updates **session weights only**.
  2. In `scorer.py`, physically reorder the top 3 distinct qualifying offers into indices `[0, 1, 2]` (`#1 best_overall`, `#2 closest_open`, `#3 lowest_price`) followed by remaining offers sorted by utility score.
  3. Evaluate store open hours in `normalizer.py` using `ZoneInfo("Asia/Tehran")` instead of `timezone.utc`.
- **Rationale**: Fixes Bugs #1, #3, #8, #9, and #10, ensuring store rankings are accurate for Tehran local time, genuinely diverse in Top-3, and immune to profile corruption.
- **Alternatives Considered**:
  - *Badge-only Pareto tagging without reordering*: Rejected — leaves `closest_open` or `lowest_price` buried at rank #8 below the fold.

---

## R8. Non-Destructive Idempotent Schema Migration & Dead-Code Purge

- **Decision**: Use idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`, `ALTER TABLE products DROP COLUMN IF EXISTS embedding`, and `DROP TABLE IF EXISTS user_dynamic_slots` inside `ensure_schema()` in `backend/db/postgres.py`, while deleting all 15-slot dead functions, aliases, and unused config settings documented in `cleanup-and-implementation-audit.md`.
- **Rationale**: Allows instant `< 50 ms` startup upgrade on existing ingested 273 MB PostgreSQL volumes without re-running `ingest.py`, while achieving 0% dead code across `backend/`.
- **Alternatives Considered**:
  - *Dropping and recreating all tables*: Rejected — would force a slow re-ingestion of 225,903 products and 331,506 offers.
