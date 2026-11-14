# گزارش جامع ارزیابی سیستم پیشنهاددهنده (RecSys Audit Issues)

این پوشه شامل مستندات کامل، سناریوهای بازتولید (Reproduction) و شواهد خروجی سیستم پیشنهاددهندهٔ **ترب‌چیت حضوری** از دید یک کاربر واقعی است. تمامی تست‌ها به صورت جعبه سیاه (Black-Box User Testing) روی سرور محلی (`http://localhost:8000`) در تاریخ ۱۴ نوامبر ۲۰۲۶ اجرا شده‌اند.

---

## فهرست فایل‌ها و اولویت‌بندی مشکلات

| ردیف | فایل مستند | حوزه مشکل | شدت (Severity) | خلاصه مشکل |
| :---: | :--- | :--- | :---: | :--- |
| **۰** | [`00-overview-and-scenarios.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/recsys_audit_issues/00-overview-and-scenarios.md) | خلاصه و سناریوها | — | نمای کلی ۱۰ سناریوی خرید اجراشده و اولویت‌بندی رفع باگ‌ها برای داوری (۱۲۵ امتیاز Product + Intelligence) |
| **۱** | [`01-product-retrieval-and-normalization.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/recsys_audit_issues/01-product-retrieval-and-normalization.md) | نرمال‌سازی متن و بازیابی کالا | **Critical (بحرانی)** | شکست روی املای بدون فاصله («لپتاپ» در برابر «لپ تاپ»)، پیشنهاد کالای «عنوان حذف‌شده برای انتشار» (۱۱ هزار تومانی) و قفل شدن نشست روی آن |
| **۲** | [`02-accessory-spare-part-and-stock-trap.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/recsys_audit_issues/02-accessory-spare-part-and-stock-trap.md) | فیلترینگ کالای اصلی در برابر قطعه/لوازم جانبی/استوک | **Critical (بحرانی)** | پیشنهاد دیسک بازی به جای کنسول PS5، پیشنهاد «گوش چپ ایرپاد» و ایرپاد فیک ۸۳۰ هزار تومانی به جای ایرپاد اصلی، پیشنهاد «پمپ اسپرسوساز» به جای دستگاه اسپرسوساز، و اولویت دادن به گوشی‌های استوک/دست‌دوم |
| **۳** | [`03-hard-constraints-and-ui-overrides.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/recsys_audit_issues/03-hard-constraints-and-ui-overrides.md) | قیود سخت (Hard Constraints) و فیلترهای کاربر | **Critical (بحرانی)** | نادیده گرفتن شروط `require_installment`، `require_open_now`، `max_distance_km` و `max_price_toman` در عمل، همراه با ادعای اشتباه رعایت آن‌ها در متن پاسخ |
| **۴** | [`04-store-deduplication-and-utility-scoring.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/recsys_audit_issues/04-store-deduplication-and-utility-scoring.md) | تنوع فروشگاه‌ها، امتیاز مطلوبیت و نقش‌های پارِتو | **High (بالا)** | قبضه شدن ۵ ردیف اول توسط یک مغازه تکراری، سقوط امتیاز مطلوبیت (`utility_score`) به عدد ثابت `10%`، برچسب اشتباه `lowest_price` روی کالای گران‌تر، و دلایل غیرمنطقی در `why_this_shop_fa` |
| **۵** | [`05-clarification-and-multi-turn-state.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/recsys_audit_issues/05-clarification-and-multi-turn-state.md) | تعامل چندمرحله‌ای، شفاف‌سازی و بازخورد | **High (بالا)** | پرسیدن سوال شفاف‌سازی با وجود Confidence بالای ۰.۹۰، بی‌تاثیر بودن پاسخ‌های تخصصی کاربر در فیلتر محصولات، ناهماهنگی متن دستیار با `selected_product_id`، و رفتار نامطلوب روی `thumbs_down` |
| **۶** | [`06-fallback-store-and-comparison-bugs.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/recsys_audit_issues/06-fallback-store-and-comparison-bugs.md) | فروشگاه جایگزین (`/fallback`) و جدول مقایسه (`/compare`) | **Medium-High (متوسط به بالا)** | محاسبه فاصله مغازه جایگزین نسبت به مغازه اول به جای لوکیشن کاربر (`0.01 km`)، تناقض `open_stores_count: 0` با `closest_open_shop`، و عناوین تکراری/بریده‌شده در ستون‌های جدول مقایسه |

---

## خلاصه ۱۰ سناریوی تست‌شده به عنوان کاربر

1. **سناریو ۱ (خرید دقیق + قسطی + لوکیشن ولیعصر)**: *«میخوام حضوری آیفون ۱۶ نرمال ۱۲۸ گیگ بخرم، قسطی هم بده و نزدیک میدان ولیعصر باشه»*
2. **سناریو ۲ (کشف نیاز لپ‌تاپ + بودجه + تعامل ۳ مرحله‌ای)**: *«یه لپتاپ خوب برای برنامه‌نویسی و کمی بازی تا حدود ۶۰ میلیون چی پیشنهاد میدی؟»* -> انتخاب اقساط و پردازنده Intel -> درخواست برند ایسوس و رم ۱۶ گیگ
3. **سناریو ۳ (خرید کنسول بازی با تاکید بر کمترین قیمت)**: *«پلی استیشن ۵ اسلیم دیجیتال میخوام بخرم، ارزون‌ترین مغازه کجاست؟»*
4. **سناریو ۴ (خرید گوشی با قید گارانتی شرکتی)**: *«گوشی سامسونگ S24 Ultra حافظه 256 گیگابایت با گارانتی شرکتی میخوام»*
5. **سناریو ۵ (املای با فاصله «لپ تاپ» + نیاز فوری/مغازه باز)**: *«لپ تاپ لنوو یا ایسوس برای کارهای مهندسی میخوام، همین الان هم میخوام برم بخرم پس مغازه باز باشه»*
6. **سناریو ۶ (کالای حساس به اصالت + فیلترهای اسلایدر UI Overrides)**: *«ایرپاد پرو ۲ اصلی میخوام حضوری بخرم، نزدیک تجریش هستم و تا ۱۵ میلیون بودجه دارم»* (`max_distance_km=5.0`, `max_price_toman=15000000`, `require_open_now=True`)
7. **سناریو ۷ (جریان کامل S24 Ultra: شفاف‌سازی -> انتخاب رنگ و سرعت -> Thumbs Down -> Fallback -> Compare)**: تست کامل زنجیره APIها روی یک محصول مشخص
8. **سناریو ۸ (انتخاب مستقیم محصول از روی کارت `selected_product_id`)**: کلیک روی کارت لپ‌تاپ ایسوس `product_2eed351d334965fa4187740a` برای مشاهده فروشگاه‌های همان مدل
9. **سناریو ۹ (تغییر دستی وزن‌ها و قیود از طریق `/api/v1/feedback` با `weight_override`)**: تغییر وزن قیمت به `0.95` و روشن کردن هم‌زمان قید اقساط و گارانتی
10. **سناریو ۱۰ (لوازم خانگی / اسپرسوساز با سقف بودجه)**: *«اسپرسوساز خانگی خوب تا ۱۰ میلیون تومان چی بخرم؟»*
