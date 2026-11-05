---
name: beyond-chat-rtl-ux
description: >-
  Use this skill whenever designing, creating, or modifying UI/UX components,
  pages, generative UI widgets, map views, or user flows for the Torob In-Person
  Shopping Assistant (ترب‌چیت حضوری). Enforces the exact dark-mode raspberry-pink
  theme, 8-bit pixel mascot & catalog animations, Lucide icons, Vazirmatn RTL
  typography, and interactive widget patterns from `UI_Template/`.
---

# Beyond-Chat Persian RTL UX Standard (`UI_Template` Spirit & Theme)

## 1. Visual Identity, Theme Palette & Icons (Preserve 100%)
All UI work must strictly preserve the spirit, color tokens, typography, and signature animations from [`UI_Template/`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template):

- **Typography & Direction**:
  - `dir="rtl"` and `lang="fa"`, font family `'Vazirmatn'` (`letter-spacing: -0.015em`).
  - Format all prices and counts with `.toLocaleString('fa-IR')` + `تومان`.
- **Dark-Mode Surface Hierarchy**:
  - App Background: `#0c0c10` / `#0d0d12` (`bg-[#0c0c10]`)
  - Primary Card / Bubble Surface: `#14141a` / `#131318` (`border-[#22222c]` or `#24242e`)
  - Elevated / Hover Card Surface: `from-[#202030] via-[#181826] to-[#12121d]` with `border-[#36364e]`
  - Input / recessed surface: `#121218` / `#0d0d14`
- **Brand & Semantic Accent Tokens**:
  - **Torob Raspberry Pink (Primary)**: `#e9325a` (hover `#ff2d5f`, light accent `#ff4d79` / `#ff6688` / `#ff80a0`)
  - **Open / Verified / Official Shop (Emerald)**: `emerald-400` / `bg-emerald-500/15 border-emerald-500/30`
  - **Distance / Warning / Price Discrepancy (Amber)**: `amber-300` / `amber-400` (`bg-amber-500/15 border-amber-500/30`)
- **Signature Custom Components & CSS Animations (`src/index.css`)**:
  - [`TorobLogo.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/TorobLogo.tsx): 16x16 8-bit pixel-art Torob radish mascot (`pixelBob` idle animation, `pixelWiggle` thinking animation, ambient `#e9325a/25` glow).
  - [`SearchingPapersAnimation.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/SearchingPapersAnimation.tsx): Animated flipping catalog pages + scanning magnifying glass (`"غمت نباشه، دارم می‌گردم برات..."`).
  - **CSS Effects**: `.torob-gradient-border` (rotating `#e9325a -> #ff6088 -> #2a0b14` border on assistant bubbles), `.torob-frame-glow`, and `.single-electric-stroke` (traveling spark around initial hero input box).
- **Iconography (`lucide-react` + `motion/react`)**:
  - Top Header sliding pink tab bar (`layoutId="activeTabIndicator"`): `MessageSquareText` (گفتگو), `Store` (فروشگاه‌ها), `Swords` (نبرد و مقایسه مدل‌ها), `Clock` (تاریخچه و فیلترها).
  - Contextual icons: `Clock` (time), `MapPin` / `Building` / `Compass` / `Navigation` (location & wayfinding), `CreditCard` / `CheckCircle2` (TorobPay & installments), `Target` (usage), `PhoneCall` (store contact), `ShieldCheck` (warranty).

---

## 2. Core Interactive Widget Architecture (75/300 UX Points)
Keep and extend the 3-tab + 2-modal progressive disclosure architecture from `UI_Template`:

1. **Progressive Header Tabs ([`Header.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/Header.tsx))**:
   - Center tabs (`chat`, `stores`, `compare`) stay hidden on the initial hero screen and animate in (`showTabs`) once recommendations/offers are generated.
2. **Slide-Out Right Drawer ([`Sidebar.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/Sidebar.tsx))**:
   - Contains conversation history + live in-store toggles (`فقط مغازه‌های باز در این لحظه`, `پذیرنده ترب‌پی حضوری`, `خرید اقساطی / اسنپ‌پی`).
3. **Need-Discovery Clarification Widget ([`FeatureClarificationCard.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/FeatureClarificationCard.tsx))**:
   - Renders numbered cards with an `impactBadge`, quick-select option chips, AND a dedicated custom input box per question.
   - Hides the bottom chat bar (`isQuestionFormActive`) while the user answers, and collapses into an editable summary card (`ویرایش مشخصات`) after submission.
4. **Rich Assistant Turn Cards ([`ChatView.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/ChatView.tsx))**:
   - **Quick Battle Table (`comparisonTable`)**: Inline compact comparison table with `Swords` icon.
   - **Selectable Product Cards (`recommendedProducts`)**: 2-column cards with product image, badge, `bestFor` rationale, Tehran floor price (`minPrice`), and store count CTA.
   - **Collapsible In-Chat Shop Offers (`shopOffers`)**: Expandable drawer showing top nearby stores with `رسمی` badge (`isRealShop`), neighborhood/mall badge, distance in km, `lastUpdated` badge, `ترب‌پی حضوری` badge, and CTAs for `همراهی خرید` & `تماس با فروشگاه`.
5. **Stores & Geo-Discovery View ([`StoresView.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/StoresView.tsx))**:
   - Sticky product banner with Tehran floor price + neighborhood selector (`userLocation`).
   - Ranked store cards with expandable address/mall details, 4-box metadata grid (`ساعات کاری`, `گارانتی`, `شرایط اقساط`, `به‌روزرسانی`), and 1-tap `فروشگاه جایگزین` drawer.
6. **Model Battle & Comparison View ([`ComparisonView.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/ComparisonView.tsx))**:
   - Side-by-side product cards + expandable full technical spec matrix.
7. **Live In-Person Shopping Companion ([`ShoppingCompanionModal.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/ShoppingCompanionModal.tsx))**:
   - 4-step interactive stepper (`۱. مسیریابی` with Neshan/Balad/Google Maps deep links -> `۲. تست در مغازه` interactive checklist -> `۳. پرداخت و فاکتور` -> `۴. پایان خرید`) + minimizable floating bottom bar + rescue actions (`گزارش مغایرت قیمت`, `مغازه بسته بود؟ فروشگاه جایگزین`, `تماس با مغازه`).
8. **Store Contact & Transparency Modal ([`StoreContactModal.tsx`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/components/StoreContactModal.tsx))**:
   - Direct `tel:` call button, copy phone button, real `instagramHandle` & `websiteUrl` links (for the 112 verified shops), working hours, and pre-visit calling tips.

---

## 3. Planned Upgrades Over `UI_Template` (To Verify with User)
While keeping the exact visual spirit, theme, and icons of `UI_Template`:
1. **Replace Mock Data (`mockData.ts`) with Real Dataset + RecSys**:
   - Connect `PRODUCTS` and `SHOP_OFFERS` to the FastAPI + DuckDB backend (225,903 products, 331,506 offers, 6,476 shops) and the user's custom RecSys engine.
2. **Interactive Tehran Map Integration in `StoresView`**:
   - Add an open-source Leaflet / MapLibre dark-themed map alongside the store cards showing user location, store pins with price tags, and instant radius/neighborhood filtering.
3. **Indoor Mall Micro-Navigation Badges (`طبقه / راهرو / واحد`)**:
   - `UI_Template` currently has comments saying `No Floor` on summary rows; since `CHALLENGE.md` Pain Point #4 explicitly scores indoor mall navigation (`طبقه، راهرو، پلاک`), surface extracted `mallFloor` and `mallUnit` cleanly inside the expanded address card and `ShoppingCompanionModal` Step 1.
4. **Dynamic Weight / Filter Controls**:
   - Wire [`rankingEngine.ts`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template/src/utils/rankingEngine.ts) (`relevance`, `distance`, `price`, `stockFreshness`, `creditSupport`) and real `last_price_changed_at` timestamps directly to the UI controls.
