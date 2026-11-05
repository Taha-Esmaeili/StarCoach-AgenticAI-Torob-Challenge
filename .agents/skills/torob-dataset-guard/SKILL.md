---
name: torob-dataset-guard
description: >-
  Use this skill whenever inspecting, indexing, querying, or writing data
  models and pipelines for `dataset/shops.csv`, `dataset/products.csv`, and
  `dataset/offers.csv`. Enforces strict offer-vs-category separation, literal
  `"null"` handling, installment payment parsing, indoor mall address extraction,
  and 112 real-shop rules.
---

# Torob Starcoach v16 Dataset Guard

## 1. Exact Dataset Inventory (`dataset/`)
- `shops.csv` (6,476 rows, Tehran subset, max 300 products/shop):
  `address, category_names, contacts, instagram, lat, location_label, lon, name, payment_options, shop_id, supports_fast_delivery, website_url, weekly_hours`
- `products.csv` (225,903 rows):
  `brand_name, category_name, image_urls, model, persian_title, product_id, specs`
- `offers.csv` (331,506 rows):
  `description, last_price_changed_at, offer_id, price_toman, product_id, seller_title, shop_id, warranty`

## 2. Five Non-Negotiable Data Integrity Rules (20 pts Dataset + 50 pts Intelligence)

1. **Offer vs. Shop Category Separation (CRITICAL)**:
   - A store having a category in `shops.category_names` does **NOT** mean it stocks a specific product.
   - To claim a shop sells a product, there **MUST** be a matching record in `offers.csv` (`offers.product_id == products.product_id AND offers.shop_id == shops.shop_id`).
   - Only use `shops.category_names` as a explicitly labeled secondary fallback ("فروشگاه‌های هم‌صنف در این محدوده — نیازمند استعلام تلفنی") when zero direct `offers` exist nearby.

2. **Literal `"null"` String Normalization**:
   - Missing values in the CSVs are written as the literal string `"null"` (or `"[]"` for empty JSON arrays, and `""` in `offers.description`).
   - During PostgreSQL (`pgvector`) ingestion, normalize `'null'` -> `NULL` before `JSONB` parsing or filtering.

3. **Real vs. Anonymized Shops & Fake Phones**:
   - All 6,476 phone numbers in `shops.contacts` are synthetic test numbers.
   - Exactly **112 shops** have real names (`instagram != 'null' OR website_url != 'null'`: 22 with Instagram, 90 with Website); the other 6,364 shops have synthetic names. Surface Instagram/Website links prominently when present.

4. **Credit & Installment Filtering (`payment_options`)**:
   - `payment_options` is a JSON array of objects: `[{"provider_name": "ترب‌پی" | "اسنپ‌پی" | "دیجی پی" | "تارا" | "ازکی‌وام", "channel": "in_person" | "unknown", "min_price_toman": ..., "max_price_toman": ..., "category_names": [...]}]`.
   - Distinguish `channel == "in_person"` (verified in-person credit acceptance) from `channel == "unknown"` (requires confirmation).

5. **Indoor Mall Micro-Navigation Extraction (`address`)**:
   - Parse Persian address tokens (`پاساژ`, `مجتمع`, `طبقه`, `همکف`, `راهرو`, `واحد`, `پلاک`) from `shops.address` into structured fields (`mall_name`, `floor`, `unit`) so users inside complex malls (e.g., `پاساژ علاءالدین`, `پاساژ چهارسو`, `پاساژ پایتخت`) get exact indoor wayfinding.
