# Codebase Cleanup, Bug-Fix & Implementation Specification (`003-clean-adaptive-recsys`)

این سند مکمل فنی و دقیقِ [`spec.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/specs/003-clean-adaptive-recsys/spec.md) است تا هیچ کد اضافه، جدول مرده یا باگ پنهانی در پروژه باقی نماند. تغییرات به **۳ بخش تفکیک‌شده** تقسیم شده‌اند:
1. **بخش اول (`Purge Ledger`)**: هر چیزی که باید **کامل پاک شود** تا کدبیس سبک و تمیز شود.
2. **بخش دوم (`Bug-Fix Ledger`)**: هر کدی که الان **اشتباه نوشته شده یا کرش می‌کند** و باید اصلاح شود.
3. **بخش سوم (`New & Updated Capabilities`)**: تغییرات دقیق روی فایل‌های موجود برای پیاده‌سازی معماری دولایه نهایی، انتقال انتخابی ویژگی‌ها (لپ‌تاپ $\leftarrow$ گوشی)، پشتیبانی از فیچرهای آنی (مثل «استوک») و تثبیت پایان نشست.

---

## بخش اول: فهرست کامل کدها و جداول مرده که باید پاک شوند (`Purge Ledger`)

در کد فعلی، بقایای معماری قدیمی «۱۵ اسلاتی» کنار معماری جدید مانده‌اند و هیچ نقشی در تولید خروجی واقعی ندارند:

| فایل | خطوط فعلی | موردی که باید کاملاً حذف شود | دلیل حذف |
| :--- | :--- | :--- | :--- |
| [`backend/db/postgres.py`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/db/postgres.py#L51) | `#L51`, `#L79-L91` | ۱. جدول `user_dynamic_slots` (`#L79-L91`)<br>۲. ستون همواره تهی `products.embedding` (`#L51`) | جدول `user_dynamic_slots` در مسیر واقعی محصول هرگز پر یا خوانده نمی‌شود و `ingest.py` هرگز `products.embedding` را پر نمی‌کند (`NULL` در هر ۲۲۵,۹۰۳ ردیف). |
| [`backend/db/profiles.py`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/db/profiles.py#L80-L98) | `#L28-L29`, `#L80-L98`, `#L141-L198`, `#L202-L229` | ۱. تابع `find_closest_dynamic_slot_pgvector`<br>۲. کوئری‌های `SELECT`/`INSERT` روی `user_dynamic_slots` داخل `load_user_profile` و `save_user_profile`<br>۳. فیلد مرده `dynamic_slots` در پروفایل | به طور کامل با `user_trait_memory` جایگزین شده و فقط بار اضافی روی دیتابیس ایجاد می‌کند. |
| [`backend/recsys/jev_engine.py`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/recsys/jev_engine.py#L8-L52) | `#L10`, `#L19-L26`, `#L40-L52`, `#L93-L101`, `#L114`, `#L353`, `#L368-L375`, `#L413-L423`, `#L563-L570`, `#L761-L763` | ۱. `import asyncio` تکراری در خط ۱۰<br>۲. تاپل ۶ دسته‌ای هاردکدشده `VALID_DOMAINS` (`electronics`, `footwear_apparel`, ...) (`#L19-L26`, `#L413-L423`)<br>۳. دیکشنری قدیمی ۱۰ اسلاتی `FIXED_SLOT_CATALOG`<br>۴. کلاس مرده `CandidateDynamicSpec` و لیست `candidate_dynamic_specs`<br>۵. کپی‌کاری کلیدهای قدیمی (`w_score`, `w_freshness`, `w_warranty`, `w_verified_shop`, `w_mall_cluster`, `w_delivery_backup`) در `session_weights`<br>۶. تابع تکراری `check_feature_equivalence_noul` | حذف کامل هم کدهای مرده ۱۵ اسلاتی و هم تاپل دسته‌بندی هاردکدشده `VALID_DOMAINS`؛ سیستم باید بدون هیچ لیست دسته‌بندی ثابت روی هر کالای دلخواه در کاتالوگ به صورت کاملاً جنرال کار کند. |
| [`backend/recsys/deduplicator.py`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/recsys/deduplicator.py#L98-L204) | `#L98-L204` | تابع ۱۰۰ خطی مرده `upsert_dynamic_spec_slots` و ایمپورت‌های مرتبط با آن | در هیچ نقطه‌ای از اپلیکیشن فراخوانی نمی‌شود (طبق کامنت خودش فقط برای تست قدیمی نگه داشته شده بود). |
| [`backend/recsys/weights.py`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/recsys/weights.py#L26-L33) | `#L26-L33`, `#L69-L85` | ۱. تابع بی‌استفاده `compute_fusion_alpha`<br>۲. منطق نگاشت کلیدهای منسوخ (`_resolve_session_judgment` برای کلیدهای قدیمی) | پس از یکدست شدن ۵ معیار فروشگاه، هیچ کلید قدیمی در سیستم تولید نمی‌شود. |
| [`backend/recsys/clarifier.py`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/recsys/clarifier.py#L129-L152) | `#L129-L152` | تابع بی‌استفاده `map_clarification_answers_to_deltas` (مبتنی بر تطبیق کلمه‌ای هاردکدشده) و کلیدهای قدیمی `w_warranty` / `w_verified_shop` در خط ۸۵ | در `main.py` اصلاً استفاده نمی‌شود و پاسخ‌های کارت ابهام‌زدایی با خود مدل `Jev` ارزیابی می‌شوند. کلید خط ۸۵ نیز باید به `w_trust_freshness` اصلاح شود. |
| [`backend/recsys/scorer.py`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/recsys/scorer.py#L26) | `#L26`, `#L74-L78`, `#L133` | ۱. پارامتر بی‌استفاده `dynamic_slots` در `_compute_feature_vector` و `score_and_rank_offers`<br>۲. کلیدهای تکراری قدیمی در خروجی `_compute_feature_vector` (`w_freshness`, `w_score`, `w_warranty`, `w_verified_shop`) | این پارامتر در بدنه تابع هیچ استفاده‌ای ندارد. |
| [`backend/db/queries.py`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/db/queries.py#L24-L109) | `#L24-L50`, `#L77-L109`, `#L238` | ۱. ست ۴۵ کلمه‌ای استاپ‌ورد هاردکدشده `_PARTICLES_FA` (`#L24-L46`)<br>۲. عبارت باقاعده هاردکدشده `_ACCESSORY_CATEGORY_REGEX` (`#L48-L50`)<br>۳. کل تابع تطبیق زیررشته‌ای هاردکدشده `rerank_products_with_domain_traits` (`#L77-L109`) و فراخوانی‌های آن در `main.py#L29,L466,L733`<br>۴. پارامتر بی‌استفاده `query_embedding` در `search_products` (`#L238`) | حذف ۱۰۰٪ عصاهای کلیدواژه‌ای دستی؛ تشخیص لوازم جانبی، استخراج عبارات کاتالوگی و سنجش معنایی تطابق ویژگی‌ها به طور کامل به مدل تصمیم‌گیر سپرده می‌شود. |
| [`backend/main.py`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/main.py#L359) | `#L54`, `#L359`, `#L503`, `#L766` | فراخوانی آنلاین و مسدودکننده `query_vec = await embed_text_async(req.message)` در هر نوبت چت و ارسال `dynamic_slots` به `score_and_rank_offers` | یک رفت‌وبرگشت شبکه کامل (`~300ms`) در هر پیام مصرف می‌کند بدون اینکه در جستجوی کالا استفاده شود؛ انتخاب ویژگی‌های مرتبط کاربر به صورت موازی داخل همان فراخوانی اول `Jev` انجام خواهد شد. |
| [`backend/config.py`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/config.py#L62-L108) و [`.env.example`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/.env.example) | `#L62-L73`, `#L87-L96`, `#L104-L108`, `#L142-L151` | متغیرهای پیکربندی کاملاً بلااستفاده: `recsys_base_slots`, `recsys_persona_slots`, `recsys_dynamic_slots`, `recsys_default_base_weights_json`, `recsys_default_persona_weights_json`, `recsys_fusion_gamma`, `recsys_fusion_alpha_min`, `recsys_fusion_alpha_max`, `recsys_dynamic_slot_decay_lambda`, `recsys_dedup_cosine_high_threshold`, `recsys_dedup_cosine_low_threshold`, `recsys_dedup_jev_noul_threshold`, `recsys_travel_cost_per_km_toman`, `recsys_travel_coupling_lambda`, `recsys_bayesian_prior_votes` | هیچ‌کدام در منطق واقعی سیستم نقشی ندارند و تنها ۵ وزن استاندارد `recsys_default_store_weights_json` منبع حقیقت لایه فروشگاه است. |
| [`backend/tests/`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/tests/) | [`test_ingest_guard.py#L135-L155`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/tests/test_ingest_guard.py#L135-L155), [`test_recsys_math.py#L122-L123`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/tests/test_recsys_math.py#L122-L123), [`test_phase1_contracts.py#L23-L36`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/tests/test_phase1_contracts.py#L23-L36) | تست‌های مربوط به توابع و جداول حذف‌شده بالا | جایگزینی با تست‌های واقعی `user_trait_memory`، انتقال انتخابی ویژگی‌ها، فیلتر `استوک`، چیدمان پارتو و محافظ هدیه/نارضایتی. |

---

## بخش دوم: فهرست کامل باگ‌ها و کدهای اشتباه فعلی (`Bug-Fix Ledger`)

این ۱۱ مورد در کد فعلی **غلط کار می‌کنند یا خطای زمان اجرا می‌دهند** و باید اصلاح شوند:

1. **کرش `HTTP 500 AttributeError` هنگام زدن دکمه رضایت (👍):**
   - **محل باگ:** [`backend/main.py#L770`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/main.py#L770) در برابر [`backend/models/schemas.py#L175-L184`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/models/schemas.py#L175-L184) و [`UI_Template/src/api/client.ts#L298-L306`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/api/client.ts#L298-L306).
   - **علت:** `main.py` فیلد `req.target_offer_id` را می‌خواند ولی این فیلد اصلاً در مدل `FeedbackRequest` تعریف نشده است!
   - **اصلاح:** افزودن فیلدهای اختیاری `target_offer_id: str | int | None = None` و `target_product_id: str | int | None = None` به `FeedbackRequest` و `client.ts`، و ارسال سیگنال انتخاب فروشگاه هنگام کلیک کاربر روی تماس/مسیریابی فروشگاه در [`UI_Template/src/App.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/App.tsx).

2. **الصاق جعلی برچسب «منطبق با ترجیح شما» به همه کالاها + مرتب نکردن کالاها:**
   - **محل باگ:** [`backend/db/queries.py#L77-L109`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/db/queries.py#L77-L109)، [`backend/recsys/jev_engine.py#L720-L721`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/recsys/jev_engine.py#L720-L721) و [`backend/main.py#L182-L183`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/main.py#L182-L183).
   - **علت:** شرط `if not matched_prefs and traits: matched_prefs.append(traits[0]["preference"])` باعث می‌شود حتی اگر کالا هیچ ربطی به ترجیح کاربر نداشته باشد، برچسب تطابق روی کارتش بخورد! همچنین تابع `rerank_products_with_domain_traits` اصلاً `sort` انجام نمی‌دهد.
   - **اصلاح:** حذف کامل الصاق اجباری در هر ۳ فایل؛ نمایش برچسب فقط در صورت تطابق واقعی متنی یا تایید مدل تصمیم‌گیر، و اعمال واقعی امتیاز ویژگی‌ها در مرتب‌سازی.

3. **تخریب پروفایل دائمی روی دکمه نارضایتی (👎) و هاردکد شدن ضریب `0.65`:**
   - **محل باگ:** [`backend/main.py#L673-L685`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/main.py#L673-L685) و [`backend/recsys/weights.py#L238`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/recsys/weights.py#L238).
   - **علت:** در هر فراخوانی `/feedback` (حتی وقتی کاربر 👎 زده!) وزن‌های نشست با فرمول `step = max(eta * judgment.confidence, 0.65)` در پروفایل دائمی ذخیره می‌شوند.
   - **اصلاح:** پروفایل دائمی ۵ وزن فروشگاهی **فقط و فقط** روی انتخاب مثبت فروشگاه (`Contrastive Update`) یا تغییر مستقیم اسلایدر وزن‌ها (`weight_override`) آپدیت شود؛ پاسخ به کارت ابهام‌زدایی (`clarification_choice`) فقط وزن‌های **نشست جاری** را تنظیم کند و `thumbs_down` هرگز پروفایل دائمی را دستکاری نکند.

4. **هاردکد شدن سقف آستانه `0.18` بر خلاف `.env`:**
   - **محل باگ:** [`backend/recsys/weights.py#L96`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/recsys/weights.py#L96) و `#L233`.
   - **علت:** عبارت `min(float(settings.recsys_mention_score_threshold), 0.18)` مقدار `0.35` در `.env` را خنثی کرده و نویزهای کوچک `Jev` را به اشتباه به عنوان معیار ذکرشده در نظر می‌گیرد.
   - **اصلاح:** استفاده مستقیم از `settings.recsys_mention_score_threshold` بدون `min(..., 0.18)`.

5. **کور بودن جستجوی کالا و پیشنهادهای فروشگاهی نسبت به شرایط فروشنده (مثل «استوک»):**
   - **محل باگ:** [`backend/db/queries.py#L513-L530`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/db/queries.py#L513-L530) و [`backend/main.py#L364-L380`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/main.py#L364-L380).
   - **علت:** `fetch_candidate_offers` اصلاً ستون‌های `o.seller_title` و `o.description` را نمی‌خواند و `search_products` ویژگی‌های استخراج‌شده پیام فعلی و تاریخچه گزینش‌شده را در بازیابی لحاظ نمی‌کند.
   - **اصلاح:** واکشی `o.seller_title` و `o.description` در `fetch_candidate_offers`، خلاصه‌سازی وضعیت پیشنهادهای هر کالا (مثلاً وجود عبارت استوک/کارکرده در پیشنهادها) هنگام بازیابی کالا، و اعمال ضریب تطابق شرط فروشنده در رتبه‌بندی مغازه‌ها.

6. **پاک شدن کامل سابقه قبلی در یک محور با یک خرید یهویی (`Destructive Overwrite`):**
   - **محل باگ:** [`backend/recsys/deduplicator.py#L78-L93`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/recsys/deduplicator.py#L78-L93) و [`backend/db/profiles.py#L406-L419`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/db/profiles.py#L406-L419).
   - **علت:** هر ترجیح جدید روی همان محور (مثلاً `"برند"`) مقدار قبلی را با `UPDATE` بازنویسی می‌کند و `hit_count` قبلی را به نام مقدار جدید ثبت می‌کند!
   - **اصلاح:** نگهداری `(domain, source_category, aspect, preference, strength, hit_count)` به طوری که اگر `preference` یکسان بود `strength` و `hit_count` تقویت شوند، و اگر روی همان `aspect` مقدار `preference` متفاوت بود، ترجیح قبلی با ضریب زوال ملایم حفظ شود (نگهداری حداکثر ۲ ترجیح برتر در هر محور به جای حذف فوری).

7. **نام اشتباه قلمرو (`"general_retail"`) و ناقص بودن جدول `shopping_sessions` در PostgreSQL:**
   - **محل باگ:** [`backend/main.py#L701`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/main.py#L701)، [`backend/db/postgres.py#L107-L120`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/db/postgres.py#L107-L120) و [`backend/db/profiles.py#L468-L553`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/db/profiles.py#L468-L553).
   - **علت:** در خط ۷۰۱ به جای `"general"` رشته نامعتبر `"general_retail"` نوشته شده است؛ همچنین فیلدهای نشست (`active_domain`, `product_search_query`, `category_keywords`, `is_accessory_request`, `price_tier`, `min_price_toman`, `max_price_toman`, `session_weights`, `shown_store_features`) در جدول `shopping_sessions` ذخیره نمی‌شوند.
   - **اصلاح:** اصلاح پیش‌فرض به `"general"` و افزودن ستون یکپارچه `session_context_json JSONB` به جدول `shopping_sessions` تا تمام فیلدهای نشست بدون کم‌وکاست در PostgreSQL پایدار بمانند.

8. **عدم جابه‌جایی واقعی ۳ جایگاه پارتو در صدر لیست فروشگاه‌ها:**
   - **محل باگ:** [`backend/recsys/scorer.py#L158-L195`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/recsys/scorer.py#L158-L195).
   - **علت:** کد فعلی فقط به نزدیک‌ترین مغازه باز و ارزان‌ترین مغازه (که شاید در رتبه ۸ یا ۹ باشند) برچسب می‌زند اما آن‌ها را به جایگاه‌های ۲ و ۳ لیست منتقل نمی‌کند.
   - **اصلاح:** انتخاب بهترین کل در رتبه ۱، قرار دادن نزدیک‌ترین مغازه بازِ واجد شرایط در رتبه ۲، و قرار دادن ارزان‌ترین مغازه واجد شرایط در رتبه ۳ (و سپس بقیه گزینه‌ها به ترتیب امتیاز).

9. **وزن‌های نرمال‌نشده و قدیمی در اندپوینت فروشگاه جایگزین (`Fallback`):**
   - **محل باگ:** [`backend/main.py#L918-L923`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/main.py#L918-L923).
   - **علت:** پاس دادن `settings.default_base_weights` (با مجموع `2.4` و کلیدهای منسوخ) به جای وزن‌های نرمال‌شده ۵ معیاره `l1_normalize_weights(settings.default_store_weights)`.
   - **اصلاح:** استفاده از ۵ وزن استاندارد نرمال‌شده `l1_normalize_weights(settings.default_store_weights)`.

10. **محاسبه ساعت کاری فروشگاه با ساعت `UTC` به جای منطقه زمانی تهران (`Asia/Tehran`):**
    - **محل باگ:** [`backend/db/normalizer.py#L238-L240`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/backend/db/normalizer.py#L238-L240).
    - **علت:** `datetime.now(timezone.utc)` ساعت را ۳.۵ ساعت عقب‌تر از وقت تهران مقایسه می‌کند!
    - **اصلاح:** استفاده از `ZoneInfo("Asia/Tehran")` برای تشخیص دقیق روز هفته و ساعت باز بودن مغازه‌های تهران.

---

## بخش سوم: مشخصات دقیق قابلیت‌های جدید و ارتقایافته (`Clean Target Architecture`)

### ۱. بسط مفهومی بدون کلیدواژه + انتقال انتخابی ویژگی‌ها در یک فراخوانی موازی `Jev` (`jev_engine.py` + `main.py`)
- **بسط مفهومی پویا به واژگان کاتالوگ (`Dynamic Concept-to-Catalog Expansion`):** بدون هیچ دیکشنری کلیدواژه یا Regex هاردکدشده، مدل در لحظه استخراج موجودیت‌ها نیازهای غیرمستقیم و عامیانه کاربر را به اصطلاحات معادل بازار/کاتالوگ بسط می‌دهد (`catalog_search_terms`: مثلاً «صدای مترو نیاد» $\to$ `["ANC", "حذف نویز", "نویز کنسلینگ"]`، «کفش کمردرد» $\to$ `["طبی", "ارتوپدی"]`، «دست‌دوم تمیز» $\to$ `["استوک", "اوپن باکس", "کارکرده"]`) و در صورت بیان شرط بازمتن فروشگاهی/مکانی، رشته `custom_offer_criterion` را استخراج می‌کند.
- **انتقال انتخابی ویژگی‌های تاریخی:** هنگام شروع `post_chat_turn`، حداکثر ۱۲ ویژگی برتر ذخیره‌شده کاربر (از `user_trait_memory` شامل `source_category`, `aspect`, `preference`, `strength`) خوانده شده و در همان درخواست موازی `Jev` (`_call_decision_model`) با دو نوع سؤال ارزیابی می‌شوند:
  1. `is_ephemeral_or_gift` (`Noul`): تشخیص اینکه آیا خرید برای شخص دیگر (هدیه/سفارش موقت) است یا خیر.
  2. به ازای هر ویژگی ذخیره‌شده $m$، یک سؤال `Noul` (`trait_transfer_{m}`): بررسی اینکه آیا جفتِ `(aspect: preference)` یادگرفته‌شده در `source_category` از نظر ماهیت کالا، مقیاس عددی و عدم تناقض، برای درخواست فعلی کاربر قابل‌استفاده است یا خیر.
- تنها ویژگی‌هایی که `noul >= settings.recsys_trait_transfer_noul_threshold` (پیش‌فرض `0.72` در `.env`) بگیرند، به عنوان ویژگی‌های تاریخیِ فعال انتخاب می‌شوند.

### ۲. لایه کالا: بازیابی هیبریدی بدون Regex + سنجش معنایی ۱۰۰٪ مبتنی بر `Jev` + دهک قیمتی (`queries.py` + `jev_engine.py`)
- **بوست نرم در SQL (`search_products`):** بدون تکیه بر `_PARTICLES_FA` یا `_ACCESSORY_CATEGORY_REGEX`، عبارات `catalog_search_terms`، ویژگی‌های لحظه‌ای پیام فعلی و ویژگی‌های تاریخیِ تاییدشده به عنوان عبارت‌های امتیازدهنده (`CASE WHEN ... THEN 1 ELSE 0 END` روی `products.normalized_name`، `products.specs_json` و زیرکوئری `EXISTS` روی `offers.seller_title` / `offers.description`) استفاده می‌شوند تا کاندیداهای منطبق (از جمله «استوک») وارد لیست ۱۲ کاندیدای برتر شوند، بدون اینکه در نبودشان نتیجه صفر شود.
- **امتیازدهی و تشخیص تطابق معنایی ویژگی‌ها در `score_candidate_products_with_decision_model`:** خود مدل تصمیم‌گیر `Jev` با دیدن مشخصات فنی و خلاصه پیشنهادهای هر کالا قضاوت معنایی می‌کند که آیا کالا واقعاً ویژگی‌های کاربر را برآورده کرده است یا خیر (مثلاً تشخیص اینکه `6000mAh` همان «شارژدهی بالا» است)، بدون هیچ تطابق زیررشته‌ای پایتونی؛ امتیاز نهایی نیز با نزدیکیِ صدک قیمتی کالا در دسته به دهک قیمتی کاربر ($\pi_{u,d}$) هنگام عدم اعلام بودجه صریح ترکیب می‌شود.

### ۳. لایه فروشگاه: ۵ معیار عددی پایه + ۱ اسلات بازمتن `w_offer_custom` + چیدمان پارتو (`jev_engine.py` + `weights.py` + `scorer.py`)
- حفظ کامل ۵ معیار مستقل عددی فروشگاهی (`w_price`, `w_distance`, `w_open_now`, `w_trust_freshness`, `w_installment`) با Sparse Override بر مبنای آستانه واقعی `.env`.
- **اسلات بازمتن پیشنهاد و مغازه (`w_offer_custom`):** هرگاه کاربر شرط غیرعددی/بازمتنی درباره مغازه یا پیشنهاد فروشنده بیان کند (`custom_offer_criterion` غیرتهی باشد؛ مثل محله/پاساژ هدف متفاوت از GPS فعلی نظیر «سمت چارسو»، پارت‌نامبر `ZAA`، رنگ، مهلت تست یا گرید استوک/پلمپ)، یک فراخوانی دسته‌ای موازی `Jev` روی حداکثر ۱۵ پیشنهاد کاندیدای برتر (شامل `shop_name`, `address`, `mall_name`, `seller_title`, `description`, `warranty`) نمره معنایی $f_{o,\text{custom}} \in [0, 1]$ را تولید کرده و وزن `w_offer_custom` در رتبه‌بندی فروشگاه‌ها اعمال می‌گردد (در کوئری‌های عادی بدون شرط خاص فروشگاهی، هزینه شبکه آن صفر است).
- چیدمان واقعی پارتو در اندیس‌های `[0, 1, 2]` خروجی `score_and_rank_offers`.

### ۴. تثبیت پایان نشست و یادگیری ایمن (`deduplicator.py` + `profiles.py` + `weights.py` + `main.py`)
- **محافظ هدیه و موقت:** اگر `is_ephemeral_or_gift >= settings.recsys_ephemeral_gift_noul_threshold` (پیش‌فرض `0.60`) باشد، هیچ نوشتنی روی `user_trait_memory` و `price_percentiles_json` انجام نمی‌شود.
- **اینرسی و نگهداری Top-2 در `user_trait_memory`:** افزودن ستون‌های `source_category TEXT` و `strength DOUBLE PRECISION` به `user_trait_memory`. در پایان نوبت (با ضریب محافظه‌کارانه `0.15`) و در هنگام انتخاب واقعی کالا/فروشگاه (با ضریب تاییدشده `0.35`)، `strength` ویژگی فعال تقویت می‌شود و ترجیح رقیب روی همان محور ضربدر ضریب زوال `0.92` می‌گردد (نگهداری حداکثر ۲ ترجیح برتر در هر محور و سقف ۱۲ ویژگی فعال در هر قلمرو).
- **دهک قیمتی نسبی (`price_percentiles_json` در `user_profiles`):** ذخیره `{domain: {"percentile": float, "count": int}}` و به‌روزرسانی با اینرسی لگاریتمی هنگام انتخاب کالا/فروشگاه.
- **یادگیری مقایسه‌ای ۵ وزن فروشگاهی (`update_store_weights_contrastive`):** ذخیره خلاصه `feature_scores` فروشگاه‌های نمایش‌داده‌شده در `session` و اجرای فرمول تفاضلی $p_{u,k} \leftarrow \operatorname{clip}(p_{u,k} + \eta (f_{o^*,k} - \bar{f}_{\mathcal{S},k}), 0.10, 1.00)$ هنگام انتخاب فروشگاه / ثبت 👍 روی پیشنهاد در `/api/v1/feedback`.
