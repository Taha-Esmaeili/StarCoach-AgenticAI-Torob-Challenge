# Project Constitution — Torob Smart In-Person Shopping Assistant (ترب‌چیت حضوری)

**Version**: 1.0.0 | **Ratified**: 2026-11-06 | **Rubric Target**: 300 / 300 Points

---

## Principle 1: 300-Point Rubric Alignment & Beyond-Chat RTL UX (150 Points)
- **Beyond Chat First (75 pts UX + 75 pts Product)**: The assistant MUST NOT trap users in wall-of-text chat. Every shopping turn MUST surface interactive, mobile-first Persian RTL (`dir="rtl"`, `Vazirmatn`) UI widgets inherited from [`UI_Template/`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template):
  - Numbered Need-Discovery Clarification Cards ([`FeatureClarificationCard.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/FeatureClarificationCard.tsx))
  - Selectable Product Recommendation Cards & Inline Model Battle Tables ([`ChatView.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/ChatView.tsx), [`ComparisonView.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/ComparisonView.tsx))
  - Ranked Store Cards + Interactive Dark-Mode Tehran Map ([`StoresView.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/StoresView.tsx))
  - 4-Step Live Shopping Companion & Rescue Bar ([`ShoppingCompanionModal.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/ShoppingCompanionModal.tsx))
  - Store Contact & Pre-Visit Transparency Modal ([`StoreContactModal.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/StoreContactModal.tsx))
- **Visual Identity Lock**: Preserve the `#0c0c10` dark canvas, `#e9325a` Torob raspberry-pink accent, 8-bit [`TorobLogo.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/TorobLogo.tsx), and [`SearchingPapersAnimation.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/SearchingPapersAnimation.tsx).

## Principle 2: Jev System One Decision Model & 15-Parameter Adaptive RecSys (50 Points Intelligence)
- **Judgments in `Jev`, Decisions in Code**: Follow [`JEV_MODEL_AND_RECSYS_REPORT.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/JEV_MODEL_AND_RECSYS_REPORT.md) and [`.agents/skills/typesafe-ai/SKILL.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/.agents/skills/typesafe-ai/SKILL.md). Use parallel `Score`, `Noul`, and `Choice` primitives (`POST /v1/systemone` via `typesafe-sdk` with automatic OpenAI-compatible fallback) to evaluate user intent in a single pass.
- **Partitioned 15-Slot Utility Vector**:
  1. **5 Global Base Slots ($k \in \{1..5\}$)**: Price Advantage, Proximity/Travel Speed, Open-Now Timing Fit, Price Freshness & Shop Trust, In-Person Credit/Installment.
  2. **5 Cross-Category Persona Slots ($k \in \{6..10\}$)**: Official Brand Affinity, Warranty Strictness, Specialized Mall Hub Preference, Fast-Delivery Readiness, Budget Tier Affinity.
  3. **5 Dynamic Category/Session Spec Slots ($k \in \{11..15\}$)**: Extracted from user prompts & `products.specs`, deduplicated via Stage-1 Embedding cosine similarity ($> 0.80$) + Stage-2 parallel `Jev` `Noul` equivalence check ($0.65\text{–}0.80$).
- **Two-Layer Weight Normalization**: Keep stored user weights unconstrained in $[0, 1]^{15}$ in the database (preventing dilution), and L1-normalize active weights to $\sum_{k=1}^{15} \hat{w}_k(u, q) = 1$ only at query-time ranking so utility $U(u, q, i) \in [0, 1]$.
- **Anti-Fatigue Clarification Policy**: Trigger `FeatureClarificationCard` **at most once** per shopping mission on Turn 1 when effective confidence $\text{EffConf}_k < 0.45$; re-trigger a second targeted clarification **only** if the user clicks 👎 (`ThumbsDown`) or `Jev` detects `user_dissatisfied.noul >= 0.70`.

## Principle 3: Torob Dataset Integrity & Transparency Guard (20 Points Dataset)
- **Strict `offers.csv` vs. `shops.category_names` Separation**: A shop is ONLY shown as stocking a product if a join record exists in `offers.csv` (`offers.product_id == products.product_id AND offers.shop_id == shops.shop_id`).
- **Information Transparency**: Clearly distinguish `price_toman` (registered price), `last_price_changed_at` (relative freshness badge), and unconfirmed live stock (requiring phone confirmation via `StoreContactModal`). Never fabricate missing (`"null"`) working hours or warranties.
- **112 Real Shops & Indoor Mall Micro-Guide**: Surface `رسمی` badge + real `instagram`/`website_url` for the 112 verified shops, and extract `پاساژ / طبقه / راهرو / واحد` from `shops.address`.

## Principle 4: Ponytail Simplicity & Verification Discipline (`/ponytail` + `/deep-interview`)
- **Smallest Complete Solution**: Every module must solve its exact spec requirement with minimal code, zero speculative abstractions, and one small test or assert-based self-check for non-trivial logic.
- **User Verification Gate**: Never alter product scope or architecture without verifying with the user first.
- **Phased Execution Priority**: Core local data engine, `Jev` RecSys, and `UI_Template` integration come first; **Liara deployment is strictly the final phase**.

## Principle 5: Dual-Base Git Workflow & 3-Gate Approvals (`/git-workflow`)
- **Branch Hierarchy**: `main` (releases only) and `develop` (integration base). Every task executes in a single-purpose topic branch (`feature/*`, `fix/*`, `chore/*`) branched from and targeting `develop`.
- **Mandatory 3-Gate Approval**: Always stop for explicit user approval at **Gate 1 (Commit)**, **Gate 2 (Push)**, and **Gate 3 (Pull Request)**.
