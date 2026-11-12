# Phase 1 Interface Contracts: Two-Stage Jev RecSys & REST API

**Feature**: `002-jev-domain-recsys` | **Date**: 2026-11-12 | **Spec**: [spec.md](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/specs/002-jev-domain-recsys/spec.md)

---

## 1. Internal System-One (`Jev`) Parallel Request Contract (`POST /v1/systemone`)

### A. Turn Intent & 5-Criteria Evaluation Request
Sent once per user message in `evaluate_turn_with_jev`:

```json
{
  "model": "jev-latest",
  "state": {
    "user_message": "یه کفش پیاده‌روی با کفی طبی می‌خوام که ارزون‌ترین قیمت تهران باشه",
    "previous_category": null
  },
  "questions": {
    "domain": {
      "type": "choice",
      "instructions": "Which commerce domain does the shopper's request belong to?",
      "criteria": {
        "electronics": "Phones, laptops, headphones, chargers, cameras, or digital gadgets",
        "footwear_apparel": "Shoes, sneakers, boots, clothing, bags, or wearable fashion",
        "home_kitchen": "Home appliances, kitchenware, furniture, or decor",
        "sports_outdoors": "Scooters, bicycles, fitness gear, or camping equipment",
        "beauty_health": "Cosmetics, skincare, perfumes, or personal health devices",
        "tools_auto": "Hardware tools, car accessories, or industrial equipment",
        "culture_toys": "Books, stationery, board games, or toys",
        "general": "Other general retail items"
      }
    },
    "needs_clarification": {
      "type": "noul",
      "instructions": "Is the shopper's request too broad to recommend a specific product without asking about budget or usage?"
    },
    "user_dissatisfied": {
      "type": "noul",
      "instructions": "Is the shopper expressing dissatisfaction or rejection toward previous recommendations?"
    },
    "require_open_now": {
      "type": "noul",
      "instructions": "Does the shopper explicitly demand a store that is open right now for immediate pickup?"
    },
    "require_installment": {
      "type": "noul",
      "instructions": "Does the shopper explicitly require installment or credit payment (TorobPay, SnappPay, etc.)?"
    },
    "require_warranty": {
      "type": "noul",
      "instructions": "Does the shopper explicitly require an official warranty as a strict condition?"
    },
    "w_price": {
      "type": "score",
      "instructions": "Does the shopper prioritize getting the lowest price in their message?",
      "criteria": [
        "The shopper did not mention price or budget.",
        "The shopper mildly prefers a reasonable price or mentioned a budget limit.",
        "The shopper strongly emphasizes getting the cheapest or lowest possible price."
      ]
    },
    "w_distance": {
      "type": "score",
      "instructions": "Does the shopper prioritize close physical proximity or fast access in their message?",
      "criteria": [
        "The shopper did not mention distance, neighborhood, or urgency.",
        "The shopper mentioned a neighborhood or prefers a nearby store.",
        "The shopper strongly emphasizes the closest store or fastest immediate access."
      ]
    },
    "w_open_now": {
      "type": "score",
      "instructions": "Does the shopper prioritize stores that are open at this moment?",
      "criteria": [
        "The shopper did not mention store opening hours or visiting right now.",
        "The shopper plans to visit today.",
        "The shopper strongly emphasizes visiting an open store immediately right now."
      ]
    },
    "w_trust_freshness": {
      "type": "score",
      "instructions": "Does the shopper prioritize store reputation, official status, warranty, or fresh price updates?",
      "criteria": [
        "The shopper did not mention warranty, store authenticity, or price freshness.",
        "The shopper prefers a reliable store or warranty.",
        "The shopper strongly emphasizes official shops, valid warranty, or verified fresh prices."
      ]
    },
    "w_installment": {
      "type": "score",
      "instructions": "Does the shopper prioritize installment or credit payment options?",
      "criteria": [
        "The shopper did not mention installment or credit payment.",
        "The shopper asks if installment payment is available.",
        "The shopper strongly emphasizes buying via installment or TorobPay/SnappPay."
      ]
    }
  }
}
```

---

## 2. Public FastAPI REST Contracts (100% Backward-Compatible with `UI_Template`)

### A. `POST /api/v1/chat/turn`
- **Request (`ChatTurnRequest`)**: Unchanged (`session_id`, `user_id`, `message`, `user_location`, `ui_overrides`, `selected_product_id`).
- **Execution Guarantees**:
  1. Evaluates turn intent, domain, and 5 store criteria via `Jev`.
  2. Reads top-5 relevant domain traits for `(req.user_id, domain)` from `user_trait_memory`.
  3. Searches and re-ranks candidate products using both current query and domain traits (surfacing matched user traits in `RecommendedProductItem.best_for_fa` / `pros_fa`).
  4. Computes non-diluted L1 store weights (`sum == 1.0`) and scores physical store offers from `offers.csv`.
  5. Schedules `sync_user_domain_traits` via `FastAPI BackgroundTasks` so trait persistence adds `0 ms` to response time.
  6. Does **not** mutate `user_profiles.base_weights` from chat text.
- **Response (`ChatTurnResponse`)**: Unchanged Pydantic schema (`session_id`, `assistant_text`, `widget_type`, `clarification_card`, `recsys_state`, `recommended_products`, `stores`, `comparison_matrix`, `follow_up_chips`).

### B. `POST /api/v1/feedback`
- **Request (`FeedbackRequest`)**: Unchanged (`session_id`, `user_id`, `feedback_type`, `selected_option_id`, `clarification_answers`, `weight_overrides`, `hard_constraints`, `user_location`, plus optional `selected_offer_id`).
- **Execution Guarantees**:
  - Updates `user_profiles.base_weights` via revealed-preference contrastive delta (or explicit slider/clarification delta) and re-ranks stores immediately.
