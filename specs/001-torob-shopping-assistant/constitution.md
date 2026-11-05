# Project Constitution — Torob Smart In-Person Shopping Assistant (ترب‌چیت حضوری)

See canonical constitution at [`.specify/memory/constitution.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/.specify/memory/constitution.md).

## Core Invariants Summary
1. **300-Point Rubric Alignment & Beyond-Chat RTL UX (150 pts)**: Mobile-first Persian RTL (`dir="rtl"`, `Vazirmatn`) built on [`UI_Template/`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/UI_Template) (`#0c0c10` / `#e9325a`, 8-bit `TorobLogo`, `SearchingPapersAnimation`).
2. **Jev System One Decision Model & 15-Parameter Adaptive RecSys (50 pts)**: `5 Global Base + 5 Cross-Category Persona + 5 Dynamic Category Spec` slots (`[0, 1]` unconstrained in DB, L1-normalized to $\sum \hat{w}_k = 1$ at query time), Confidence-Gated Fusion, Dealbreaker Multiplier $\Phi(i)$, Net Travel Coupling, Hybrid Embedding + `Jev` `Noul` deduplication, and Anti-Fatigue 1-Time + Dissatisfaction Clarification policy.
3. **Torob Dataset Integrity Guard (20 pts)**: Strict `offers.csv` vs. `shops.category_names` separation, `"null"` literal normalization, 112 real shops badge, and indoor mall wayfinding (`پاساژ / طبقه / واحد`).
4. **Ponytail & Phased Priority (40 pts Tech + 40 pts Deploy)**: Minimal, clean code with self-checks; **Liara deployment is strictly the final phase**.
5. **Dual-Base Git Workflow (`/git-workflow`)**: Single-purpose branches targeting `develop` with 3-Gate user approval.
