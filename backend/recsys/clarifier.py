"""Anti-Fatigue Clarification Policy ("Ask Once; Re-Ask Only on Dissatisfaction").

Enforces `FR-011` and `SC-004` via `.env` thresholds:
- Rule 1 (Initial Low-Confidence Gate): Trigger `FeatureClarificationCard` at most ONCE on Turn 1
  (`clarification_count == 0`) when `effective_confidence < RECSYS_CLARIFY_CONFIDENCE_THRESHOLD` (0.45).
- Rule 2 (Dissatisfaction Retry Gate): Once `clarification_count == 1`, NEVER ask again during normal
  conversation. Re-trigger a second targeted clarification (`clarification_count: 1 -> 2`) ONLY if the
  user explicitly clicks 👎 (`thumbs_down`) OR `Jev` detects `user_dissatisfied.noul >= 0.70`.
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
) -> tuple[bool, int]:
    """Determine whether to display `FeatureClarificationCard` and return `(should_ask, next_count)`."""
    max_rounds = settings.recsys_max_clarification_rounds
    if clarification_count >= max_rounds:
        return False, clarification_count

    # Turn 1 Gate: Ask at most once initially when Jev detects broad/ambiguous intent (`needs_clarification >= 0.70`)
    # or when effective_confidence falls below the configured threshold
    if clarification_count == 0:
        if (
            needs_clarification_noul >= settings.recsys_dissatisfied_noul_threshold
            or effective_confidence < settings.recsys_clarify_confidence_threshold
        ):
            return True, 1
        return False, 0

    # Dissatisfaction-Triggered Second Chance (only when clarification_count == 1)
    is_dissatisfied = explicit_thumbs_down or (
        dissatisfied_noul >= settings.recsys_dissatisfied_noul_threshold
    )
    if clarification_count == 1 and is_dissatisfied:
        return True, 2

    return False, clarification_count


def build_clarification_card(
    category_name: str,
    clarification_round: int,
) -> ClarificationCardPayload:
    """Build a rich Persian RTL `ClarificationCardPayload` compatible with both API contracts and `UI_Template`."""
    cat_title = category_name or "محصول مورد نظر"
    if clarification_round <= 1:
        question_fa = (
            f"برای اینکه دقیق‌ترین فروشگاه و مدل «{cat_title}» رو در تهران بهتون پیشنهاد بدم، "
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
            label_fa="خرید قسطی حضوری (ترب‌پی/اسنپ‌پی) و گارانتی معتبر",
            weight_deltas={"w_installment": 0.95, "w_warranty": 0.90, "w_verified_shop": 0.85},
        ),
    ]

    questions = [
        FeatureQuestionItem(
            id="timing",
            title="زمان و فوریت خرید حضوری",
            question="کی قصد مراجعه به فروشگاه و خرید حضوری دارید؟",
            impact_badge="بررسی باز بودن فروشگاه و فاصله مکانی",
            icon_type="time",
            options=[
                "همین الان (نزدیک‌ترین مغازه باز)",
                "امروز عصر یا فردا",
                "زمان مهم نیست، ارزان‌ترین مغازه تهران",
            ],
            placeholder="مثلاً: تا یک ساعت دیگه سمت ولیعصر هستم...",
        ),
        FeatureQuestionItem(
            id="payment",
            title="نحوه پرداخت و ضمانت",
            question="آیا نیاز به خرید اقساطی حضوری یا گارانتی شرکتی خاص دارید؟",
            impact_badge="فیلتر پذیرندگان ترب‌پی / اسنپ‌پی و گارانتی رسمی",
            icon_type="payment",
            options=[
                "پرداخت نقدی (کف قیمت بازار)",
                "خرید قسطی حضوری با ترب‌پی / اسنپ‌پی",
                "فقط فروشگاه رسمی با گارانتی ۱۸ ماهه",
            ],
            placeholder="مثلاً: قسطی ۴ ماهه بدون ضامن...",
        ),
    ]

    return ClarificationCardPayload(
        question_fa=question_fa,
        category=cat_title,
        category_title=cat_title,
        clarification_round=clarification_round,
        max_rounds=settings.recsys_max_clarification_rounds,
        options=options,
        questions=questions,
    )


def map_clarification_answers_to_deltas(
    selected_option_id: str | None = None,
    answers: dict[str, str] | None = None,
) -> dict[str, float]:
    """Translate 1-tap clarification pill or form answers into unconstrained weight deltas."""
    deltas: dict[str, float] = {}
    if selected_option_id == "opt_fastest":
        deltas.update({"w_distance": 0.95, "w_open_now": 0.92, "w_price": 0.35})
    elif selected_option_id == "opt_cheapest":
        deltas.update({"w_price": 0.96, "w_distance": 0.25})
    elif selected_option_id == "opt_installment_warranty":
        deltas.update({"w_installment": 0.95, "w_warranty": 0.90, "w_verified_shop": 0.85})

    for ans in (answers or {}).values():
        if "نزدیک" in ans or "الان" in ans:
            deltas.update({"w_distance": 0.95, "w_open_now": 0.92})
        if "ارزان" in ans or "کف قیمت" in ans or "نقدی" in ans:
            deltas.update({"w_price": 0.95})
        if "قسطی" in ans or "ترب‌پی" in ans or "اسنپ‌پی" in ans:
            deltas.update({"w_installment": 0.95})
        if "گارانتی" in ans or "رسمی" in ans:
            deltas.update({"w_warranty": 0.90, "w_verified_shop": 0.85})

    return deltas
