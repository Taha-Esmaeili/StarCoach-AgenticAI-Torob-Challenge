"""Anti-Fatigue Clarification Policy ("Ask Once; Re-Ask Only on Dissatisfaction").

Zero hardcoded category biases or keyword matchers:
- Rule 1 (Initial Low-Confidence Gate): Trigger `FeatureClarificationCard` at most ONCE on Turn 1
  (`clarification_count == 0`) when `needs_clarification >= 0.70` or `effective_confidence < 0.45`.
- Rule 2 (Dissatisfaction Retry Gate): Re-trigger a second targeted clarification (`1 -> 2`) ONLY if
  the user explicitly clicks 👎 (`thumbs_down`) OR `Jev` detects `user_dissatisfied.noul >= 0.70`.
- Hard Cap: Never exceed `RECSYS_MAX_CLARIFICATION_ROUNDS` (2).
"""

from typing import Any

from backend.config import settings
from backend.models.schemas import (
    ClarificationCardPayload,
    ClarificationOption,
    FeatureQuestionItem,
)


def should_trigger_clarification(
    effective_confidence: float,
    clarification_count: int,
    explicit_thumbs_down: bool = False,
    dissatisfied_noul: float = 0.0,
    needs_clarification_noul: float = 0.0,
    intent_choice: str = "clarification",
    is_continuation: bool = False,
) -> tuple[bool, int]:
    """Determine whether to display `FeatureClarificationCard` and return `(should_ask, next_count)`."""
    max_rounds = settings.recsys_max_clarification_rounds
    if clarification_count >= max_rounds:
        return False, clarification_count

    if clarification_count == 0:
        if explicit_thumbs_down:
            return True, 1
        if is_continuation:
            if dissatisfied_noul >= settings.recsys_dissatisfied_noul_threshold:
                return True, 1
            return False, 0
        if effective_confidence < settings.recsys_clarify_confidence_threshold:
            return True, 1
        if needs_clarification_noul >= settings.recsys_dissatisfied_noul_threshold and (
            intent_choice in ("clarification", "product_discovery")
            or effective_confidence < 0.78
        ):
            return True, 1
        return False, 0

    is_dissatisfied = explicit_thumbs_down or (
        dissatisfied_noul >= settings.recsys_dissatisfied_noul_threshold
    )
    if clarification_count == 1 and is_dissatisfied:
        return True, 2

    return False, clarification_count


def build_clarification_card(
    category_name: str,
    clarification_round: int,
    custom_questions: list[dict[str, Any]] | None = None,
) -> ClarificationCardPayload:
    """Build a category-neutral Persian RTL `ClarificationCardPayload` with optional dynamic item questions."""
    cat_title = category_name or "محصول مورد نظر"
    if clarification_round <= 1:
        question_fa = (
            f"برای اینکه دقیق‌ترین فروشگاه و گزینه «{cat_title}» رو در تهران بهتون پیشنهاد بدم، "
            "کدوم مورد براتون اولویت بیشتری داره؟"
        )
    else:
        question_fa = (
            f"متوجه شدم پیشنهادهای قبلی دقیقاً مطابق نظرتون نبود. برای اصلاح فوری نتایج «{cat_title}»، "
            "کدوم معیار رو تغییر بدیم؟"
        )

    options = [
        ClarificationOption(
            option_id="opt_fastest",
            label_fa="نزدیک‌ترین مغازه باز (حداقل مسافت و زمان)",
            weight_deltas={"w_distance": 0.95, "w_open_now": 0.92, "w_price": 0.35},
        ),
        ClarificationOption(
            option_id="opt_cheapest",
            label_fa="کمترین قیمت ممکن در کل تهران",
            weight_deltas={"w_price": 0.96, "w_distance": 0.25},
        ),
        ClarificationOption(
            option_id="opt_installment_warranty",
            label_fa="خرید قسطی حضوری (ترب‌پی/اسنپ‌پی) و فروشگاه معتبر",
            weight_deltas={"w_installment": 0.95, "w_trust_freshness": 0.92},
        ),
    ]

    questions: list[FeatureQuestionItem] = [
        FeatureQuestionItem(
            id="timing",
            title="زمان و اولویت خرید حضوری",
            question="کی قصد مراجعه به فروشگاه دارید و چه معیاری برایتان مهم‌تر است؟",
            impact_badge="تنظیم اولویت مسافت، باز بودن فروشگاه و قیمت",
            icon_type="time",
            options=[
                "همین الان (نزدیک‌ترین مغازه باز)",
                "امروز عصر یا فردا",
                "زمان مهم نیست، ارزان‌ترین مغازه تهران",
            ],
            placeholder="مثلاً: تا یک ساعت دیگه حضوری می‌رم...",
        ),
    ]

    if custom_questions:
        for cq in custom_questions[:1]:
            opts = [str(o).strip() for o in (cq.get("options") or []) if str(o).strip()]
            if cq.get("question") and len(opts) >= 2:
                questions.append(
                    FeatureQuestionItem(
                        id=str(cq.get("id") or "item_pref"),
                        title=str(cq.get("title") or f"ویژگی مهم {cat_title}"),
                        question=str(cq["question"]),
                        impact_badge=f"تطبیق دقیق مشخصات در دسته {cat_title}",
                        icon_type="usage",
                        options=opts[:4],
                        placeholder="توضیح دلخواه شما درباره مدل یا ویژگی مورد نظر...",
                    )
                )

    if len(questions) < 2:
        questions.append(
            FeatureQuestionItem(
                id="payment",
                title="نحوه پرداخت و اعتبار فروشگاه",
                question="شرایط پرداخت و اعتبار فروشگاه چقدر برایتان اهمیت دارد؟",
                impact_badge="بررسی پذیرندگان ترب‌پی / اسنپ‌پی و اعتبار فروشنده",
                icon_type="payment",
                options=[
                    "پرداخت نقدی (کف قیمت بازار)",
                    "خرید قسطی حضوری با ترب‌پی / اسنپ‌پی",
                    "فقط فروشگاه رسمی با ضمانت اصالت و سلامت کالا",
                ],
                placeholder="مثلاً: خرید اقساطی یا فروشگاه تاییدشده...",
            )
        )

    return ClarificationCardPayload(
        question_fa=question_fa,
        category=cat_title,
        category_title=cat_title,
        clarification_round=clarification_round,
        max_rounds=settings.recsys_max_clarification_rounds,
        options=options,
        questions=questions,
    )
