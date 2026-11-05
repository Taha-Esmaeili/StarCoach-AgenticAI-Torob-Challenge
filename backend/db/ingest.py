"""Fast CSV-to-PostgreSQL (`pgvector` + `pg_trgm`) ingestion pipeline using binary COPY."""

import argparse
import asyncio
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import asyncpg

from backend.config import settings
from backend.db.normalizer import (
    clean_null_str,
    extract_mall_micro_guide,
    extract_primary_phone,
    normalize_persian_text,
    parse_payment_options,
    parse_product_specs,
    parse_warranty,
    safe_json_loads,
)
from backend.db.postgres import INDEX_DDL, get_schema_ddl

# Increase CSV field size limit for large product specs JSON
csv.field_size_limit(sys.maxsize)


def _parse_timestamptz(raw: str | None) -> datetime | None:
    cleaned = clean_null_str(raw)
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
    except Exception:
        return None


def _iter_shops_records(shops_csv: Path) -> list[tuple[Any, ...]]:
    records: list[tuple[Any, ...]] = []
    with shops_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            shop_id = clean_null_str(row.get("shop_id"))
            if not shop_id:
                continue
            name = clean_null_str(row.get("name")) or "فروشگاه"
            norm_name = normalize_persian_text(name)
            lat = float(clean_null_str(row.get("lat")) or settings.default_user_lat)
            lon = float(clean_null_str(row.get("lon")) or settings.default_user_lng)
            location_label = clean_null_str(row.get("location_label"))
            address = clean_null_str(row.get("address"))
            mall = extract_mall_micro_guide(address)

            contacts_list, primary_phone = extract_primary_phone(row.get("contacts"))
            payment_list, has_in_person, providers = parse_payment_options(row.get("payment_options"))
            weekly_hours = safe_json_loads(row.get("weekly_hours"), {})
            category_names = safe_json_loads(row.get("category_names"), [])

            website_url = clean_null_str(row.get("website_url"))
            instagram = clean_null_str(row.get("instagram"))
            is_real_shop = bool(website_url is not None or instagram is not None)

            fast_del_raw = clean_null_str(row.get("supports_fast_delivery"))
            supports_fast_delivery = str(fast_del_raw or "").lower() in ("true", "1", "yes")

            # Deterministic realistic shop score in [4.1, 4.9] based on real shop status + hash
            h_val = sum(ord(c) for c in shop_id) % 9
            score = 4.8 if is_real_shop else round(4.1 + (h_val * 0.08), 1)
            votes_count = 85 if is_real_shop else (12 + (h_val * 7))

            records.append(
                (
                    shop_id,
                    name,
                    norm_name,
                    lat,
                    lon,
                    location_label,
                    address,
                    mall["mall_name"],
                    mall["floor_label"],
                    mall["unit_label"],
                    mall["note_fa"],
                    json.dumps(contacts_list, ensure_ascii=False),
                    primary_phone,
                    score,
                    votes_count,
                    supports_fast_delivery,
                    json.dumps(payment_list, ensure_ascii=False),
                    has_in_person,
                    providers,
                    json.dumps(weekly_hours, ensure_ascii=False),
                    json.dumps(category_names, ensure_ascii=False),
                    website_url,
                    instagram,
                    is_real_shop,
                )
            )
    return records


async def ingest_all(dataset_dir: Path | None = None, verify: bool = True) -> dict[str, Any]:
    """Ingest shops.csv, offers.csv, and products.csv into PostgreSQL + pgvector."""
    t0 = time.perf_counter()
    ds_dir = dataset_dir or settings.torob_dataset_dir
    shops_csv = ds_dir / "shops.csv"
    products_csv = ds_dir / "products.csv"
    offers_csv = ds_dir / "offers.csv"

    conn = await asyncpg.connect(dsn=settings.asyncpg_dsn)
    try:
        await conn.execute(get_schema_ddl(settings.embedding_dim))
        await conn.execute("TRUNCATE TABLE offers, products, shops RESTART IDENTITY CASCADE;")

        # 1. Ingest shops.csv (6,476 rows)
        shop_records = _iter_shops_records(shops_csv)
        await conn.copy_records_to_table(
            "shops",
            records=shop_records,
            columns=[
                "shop_id",
                "name",
                "normalized_name",
                "latitude",
                "longitude",
                "location_label",
                "address",
                "mall_name",
                "floor_label",
                "unit_label",
                "mall_note",
                "contacts_json",
                "primary_phone",
                "score",
                "votes_count",
                "supports_fast_delivery",
                "payment_options_json",
                "has_in_person_installment",
                "installment_providers",
                "weekly_hours_json",
                "category_names_json",
                "website_url",
                "instagram",
                "is_real_torob_shop",
            ],
        )

        # 2. Stream offers.csv (331,506 rows) in chunks and pre-aggregate product price/count stats
        prod_stats: dict[str, list[int]] = {}  # product_id -> [min_price, max_price, count]
        offer_batch: list[tuple[Any, ...]] = []
        offer_columns = [
            "offer_id",
            "product_id",
            "shop_id",
            "price_toman",
            "seller_title",
            "description",
            "warranty_raw",
            "has_official_warranty",
            "warranty_provider",
            "warranty_months",
            "last_price_changed_at",
        ]

        with offers_csv.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                offer_id = clean_null_str(row.get("offer_id"))
                product_id = clean_null_str(row.get("product_id"))
                shop_id = clean_null_str(row.get("shop_id"))
                if not (offer_id and product_id and shop_id):
                    continue
                price_raw = clean_null_str(row.get("price_toman"))
                price_toman = int(float(price_raw)) if price_raw else 0
                st = prod_stats.get(product_id)
                if st is None:
                    prod_stats[product_id] = [price_toman, price_toman, 1]
                else:
                    if price_toman < st[0]:
                        st[0] = price_toman
                    if price_toman > st[1]:
                        st[1] = price_toman
                    st[2] += 1

                warranty_raw = clean_null_str(row.get("warranty"))
                has_w, w_prov, w_months = parse_warranty(warranty_raw)
                ts = _parse_timestamptz(row.get("last_price_changed_at"))

                offer_batch.append(
                    (
                        offer_id,
                        product_id,
                        shop_id,
                        price_toman,
                        clean_null_str(row.get("seller_title")),
                        clean_null_str(row.get("description")),
                        warranty_raw,
                        has_w,
                        w_prov,
                        w_months,
                        ts,
                    )
                )
                if len(offer_batch) >= 50000:
                    await conn.copy_records_to_table("offers", records=offer_batch, columns=offer_columns)
                    offer_batch.clear()

        if offer_batch:
            await conn.copy_records_to_table("offers", records=offer_batch, columns=offer_columns)
            offer_batch.clear()

        # 3. Stream products.csv (225,903 rows) with pre-aggregated offer stats
        product_batch: list[tuple[Any, ...]] = []
        product_columns = [
            "product_id",
            "persian_title",
            "normalized_name",
            "model_name",
            "category_name",
            "brand_name",
            "image_url",
            "image_urls_json",
            "specs_json",
            "min_price_toman",
            "max_price_toman",
            "offer_count",
        ]

        with products_csv.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                product_id = clean_null_str(row.get("product_id"))
                if not product_id:
                    continue
                title = clean_null_str(row.get("persian_title")) or "محصول"
                model_name = clean_null_str(row.get("model"))
                category_name = clean_null_str(row.get("category_name")) or "عمومی"
                brand_name = clean_null_str(row.get("brand_name"))
                norm_name = normalize_persian_text(f"{title} {model_name or ''} {brand_name or ''}")

                img_list = safe_json_loads(row.get("image_urls"), [])
                first_img = img_list[0] if (isinstance(img_list, list) and img_list) else ""
                specs_dict = parse_product_specs(row.get("specs"))

                st = prod_stats.get(product_id, [0, 0, 0])
                product_batch.append(
                    (
                        product_id,
                        title,
                        norm_name,
                        model_name,
                        category_name,
                        brand_name,
                        str(first_img or ""),
                        json.dumps(img_list if isinstance(img_list, list) else [], ensure_ascii=False),
                        json.dumps(specs_dict, ensure_ascii=False),
                        st[0],
                        st[1],
                        st[2],
                    )
                )
                if len(product_batch) >= 40000:
                    await conn.copy_records_to_table("products", records=product_batch, columns=product_columns)
                    product_batch.clear()

        if product_batch:
            await conn.copy_records_to_table("products", records=product_batch, columns=product_columns)
            product_batch.clear()

        # 4. Build B-tree, GIN, and pg_trgm indexes + ANALYZE
        await conn.execute(INDEX_DDL)
        await conn.execute("ANALYZE shops, products, offers;")

        summary: dict[str, Any] = {
            "elapsed_sec": round(time.perf_counter() - t0, 2),
        }
        if verify:
            counts_row = await conn.fetchrow(
                """
                SELECT
                    (SELECT COUNT(*) FROM shops) AS shops,
                    (SELECT COUNT(*) FROM shops WHERE is_real_torob_shop = TRUE) AS real_shops,
                    (SELECT COUNT(*) FROM shops WHERE mall_name IS NOT NULL) AS mall_shops,
                    (SELECT COUNT(*) FROM products) AS products,
                    (SELECT COUNT(*) FROM offers) AS offers,
                    (SELECT COUNT(*) FROM offers WHERE has_official_warranty = TRUE) AS warranty_offers
                """
            )
            summary.update(dict(counts_row))
        return summary
    finally:
        await conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest Torob CSV dataset into PostgreSQL + pgvector")
    parser.add_argument("--verify", action="store_true", help="Run verification counts after ingestion")
    args = parser.parse_args()
    result = asyncio.run(ingest_all(verify=args.verify))
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
