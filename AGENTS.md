# AGENTS.md — StarCoach Agentic AI (Torob In-Person Shopping Challenge)

## 1. Mission & Judging Rubric (300 Points Total)
We are building **Torob's Smart In-Person Shopping Assistant (دستیار هوشمند خرید حضوری ترب)** for Tehran. Every product decision, spec, and line of code must directly maximize the 300-point rubric:
- **Product (75 pts)** + **UX Beyond Chat (75 pts)** = **150 pts (50%)**: Mobile-first Persian RTL experience (`dir="rtl"`) using interactive cards, filters, range sliders, and map pins—not wall-of-text chat.
- **Intelligence (50 pts)**: Need discovery & RecSys, multi-criteria shop comparison, indoor mall micro-navigation (`پاساژ/طبقه/واحد`), price freshness transparency (`last_price_changed_at`), and 1-tap fallback to alternative open stores.
- **Deployment on Liara (40 pts)** + **Technical Engineering (40 pts)** = **80 pts**: Fast, reliable container deployment with sub-second search over 225K products and 331K offers.
- **Dataset Mastery (20 pts)**: Strict separation of `offers.csv` (actual product stock) vs. `shops.category_names` (general shop category).
- **Mandatory Deliverable**: ~5-minute Demo Video (required to avoid disqualification).

---

## 2. Non-Bypassable Agent Rules & Active Skills

### A. Consultant & Deep-Interview Protocol (`/deep-interview`)
- **Do NOT make architectural, product, or scope decisions unilaterally.**
- Act as a Principal AI & Commerce Consultant: surface trade-offs concisely, recommend the highest-ROI path, and verify every planning/implementation step with the user before executing.

### B. Ponytail Mode (`/ponytail` — Level: `full`)
- **Smallest Complete Solution**: The best code is the code never written. Solve the whole task with the minimum code, zero unrequested abstractions, and zero speculative boilerplate.
- **Mandatory Check**: New non-trivial logic leaves one small test or assert-based self-check.
- **Shortcuts**: Tag intentional shortcuts with `shortcut: <the limit>, <when to upgrade>`.
- **Mandatory Reply Footer**: End every response with 1–2 lines stating:
  - **Skipped / Deferred**: What was omitted or not checked.
  - **Risk**: Any operational, data, or scoring risk the user must know.

### C. Git & GitHub Workflow (`/git-workflow`)
- **Remote**: `git@github.com:Taha-Esmaeili/StarCoach-AgenticAI-Torob-Challenge.git`
- **Dual-Base Branch Architecture**:
  - `main`: Production/release-ready code only (updated via `release/v*` PRs).
  - `develop`: Primary integration branch. All `feature/*`, `fix/*`, and `chore/*` branches originate from and target `develop`.
- **Single-Purpose Branches & Atomic Commits**: One logical job per branch; single-line Conventional Commit subjects (`<type>(<scope>): <summary>`, ≤72 chars).
- **Mandatory 3-Gate User Approval**:
  - **Gate 1 (Commit)**: Show `git status`, atomic file list, and exact `git add ... && git commit -m "..."` command. **STOP and wait for user approval.**
  - **Gate 2 (Push)**: Show branch & `git push -u origin <branch>`. **STOP and wait for user approval.**
  - **Gate 3 (PR)**: Present High-Signal PR Template targeting `develop` (or `main` for releases). **STOP and wait for user approval.**

---

## 3. Approved Tech Stack & Data Decisions

| Layer | Approved Choice | Notes |
| :--- | :--- | :--- |
| **Frontend / UX** | React 19 + Vite + Tailwind CSS v4 (`dir="rtl"`, `Vazirmatn`) | Based directly on `UI_Template/` ("ترب‌چیت حضوری" dark raspberry-pink theme `#0c0c10` / `#e9325a`, 8-bit `TorobLogo`, `SearchingPapersAnimation`, Lucide icons). |
| **Map Engine** | Open-source Leaflet / MapLibre + OSM/RTL tiles | Zero API-key friction on Liara; supports custom price pins & mall badges. |
| **Backend / API** | FastAPI (Python) | Serves REST/SSE endpoints for RecSys, geo-search, comparison, and agent turns. |
| **Data Engine** | **PostgreSQL + `pgvector` (+ Redis)** | `dataset/` (273 MB) ingested into PostgreSQL (`JSONB` + `pg_trgm` + `pgvector` HNSW for semantic search & Stage-1 feature deduplication); Redis for `<2ms` session state, anti-fatigue counters & hot profile/query caching. |
| **LLM SDK** | OpenAI-compatible SDK (`openai` / `litellm`) | Configured via `.env`: `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`. |
| **Agent & RecSys** | **Jev System One (`typesafe-sdk`) + 15-Parameter Adaptive Utility Engine** | `5 Base + 5 Persona + 5 Dynamic Spec` slots; Confidence-Gated Fusion + Embedding/Jev `Noul` deduplication (see [`JEV_MODEL_AND_RECSYS_REPORT.md`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/JEV_MODEL_AND_RECSYS_REPORT.md)). |
| **Step 4 Inquiry** | Last-Price-Update Transparency + Contact Card + 1-Tap Fallback | Live outbound calling is skipped for now; UI displays `last_price_changed_at` badge, contact details, and instant fallback store switcher. |
| **Deployment** | Liara (Dockerized service) | Single/coupled deployment optimized for 40-point Deployment score. |

---

## 4. Project Skill Registry

Always load the matching skill before working on its domain:

1. **Workspace Project Skills (`.agents/skills/`)**:
   - [`beyond-chat-rtl-ux`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/.agents/skills/beyond-chat-rtl-ux/SKILL.md): Mobile-first Persian RTL generative UI widgets, transparency badges, and `UI_Template/` theme rules.
   - [`torob-dataset-guard`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/.agents/skills/torob-dataset-guard/SKILL.md): Rules for `shops.csv` (6,476), `products.csv` (225,903), and `offers.csv` (331,506), `"null"` handling, `payment_options`, and indoor mall extraction.
   - [`typesafe-ai`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/.agents/skills/typesafe-ai/SKILL.md): Official TypeSafe AI System One (`Jev`) skill for `Choice`, `Score`, `Noul`, `Box`, speculative fan-out, and composite scoring.
   - [`speckit-teamwork`](file:///home/tahaes/Desktop/CodeCave/StarCoach/AgenticAiHackaton/Torob/.agents/skills/speckit-teamwork/SKILL.md): SpecKit (`specs/001-torob-shopping-assistant/` + `ROADMAP.md`) and `/teamwork` subagent coordination protocol.
2. **Global / Built-in Skills**:
   - `git-workflow` (`/home/tahaes/.gemini/config/skills/git-workflow/SKILL.md`)
   - `ponytail` (`/home/tahaes/.gemini/config/plugins/ponytail/skills/ponytail/SKILL.md`)
   - `generative_ui` (`/home/tahaes/.gemini/antigravity/builtin/skills/generative_ui/SKILL.md`)
   - `managing-python-dependencies` (`/home/tahaes/.gemini/config/plugins/data-agent-kit-plugin/skills/managing-python-dependencies/SKILL.md`)
