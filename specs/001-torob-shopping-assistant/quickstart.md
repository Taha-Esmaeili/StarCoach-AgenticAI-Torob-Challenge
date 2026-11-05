# Quickstart & Verification Guide: Torob Smart In-Person Shopping Assistant

**Feature Branch**: `001-torob-shopping-assistant`  
**Target Architecture**: React 19 + Vite (`UI_Template/`) + FastAPI + **PostgreSQL + `pgvector` (+ Redis)** (`backend/`) + TypeSafe AI `Jev` (`jev-1.14.0` / OpenAI-compatible System-One fallback).

---

## 1. Prerequisites & Environment Variables

Create a `.env` file in the repository root (never committed to Git):

```bash
# TypeSafe AI System One (Jev) — Optional if using OpenAI-compatible fallback
TYPESAFE_API_KEY=ts_...

# OpenAI-Compatible LLM / System-One & Embedding Endpoint (Required)
LLM_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=sk-...
LLM_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small

# PostgreSQL + pgvector & Redis Connections
DATABASE_URL=postgresql+asyncpg://torob:torob_secret@localhost:5432/torob_db
REDIS_URL=redis://localhost:6379/0

# Dataset & Server Paths
TOROB_DATASET_DIR=./dataset
PORT=8000
```

---

## 2. Step-by-Step Local Execution (For Implementation Phases)

### Step 0: Start PostgreSQL (`pgvector/pgvector:pg16`) & Redis (`redis:7-alpine`)
```bash
docker compose up -d postgres redis
```

### Step 1: Build & Verify PostgreSQL (`pgvector` + `pg_trgm`) Index from `dataset/*.csv`
Enables `CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm;`, ingests `shops.csv` (`6,476`), `products.csv` (`225,903`), and `offers.csv` (`331,506`) via fast PostgreSQL `COPY`, normalizes Persian text, parses `JSONB` columns (`weekly_hours`, `payment_options`, `warranty`, `specs`), and extracts indoor mall badges (`پاساژ`/`طبقه`/`واحد`):

```bash
uv run python -m backend.db.ingest --verify
```
**Expected Self-Check Output**:
- `shops`: `6,476` rows (`112` real Torob shops, `3,872` with extracted mall names)
- `products`: `225,903` rows (`872` categories, `pg_trgm` + `pgvector` HNSW indexes active)
- `offers`: `331,506` rows (`58,943` with parsed warranty, `330,737` with `last_price_changed_at`)
- Query benchmark: Top-20 geo+stock query completes in `< 50 ms` (`< 5 ms` on Redis cache hit).

### Step 2: Start FastAPI Backend
```bash
uv run uvicorn backend.main:app --reload --port 8000
```

### Step 3: Start React 19 + Vite Frontend (`UI_Template/`)
```bash
cd UI_Template
npm install
npm run dev
```

---

## 3. Core Acceptance Test Scenarios (300-Point Rubric Verification)

1. **Scenario A — Need Discovery & Anti-Fatigue Clarification (`US1`)**:
   - Send ambiguous query: `"یه گوشی خوب میخوام"`
   - Verify: Assistant shows `FeatureClarificationCard.tsx` (`clarification_count = 1` stored in Redis `torob:session:{id}`) + 3 Pareto-diverse options (#1 Best Overall, #2 Closest Open, #3 Lowest Price).
   - Send a second message without clicking 👎: Verify `FeatureClarificationCard` does **NOT** appear again.
   - Click 👎 (`ThumbsDown`): Verify `FeatureClarificationCard` appears one final time (`clarification_count = 2`).
2. **Scenario B — 15-Parameter Adaptive RecSys & Two-Layer Normalization (`US1` / `US2`)**:
   - Query 1: `"سریع‌ترین جایی که شارژر آیفون داره و الان بازه کجاست؟"` $\rightarrow$ Verify `w_distance` and `w_open_now` dominate $\hat{\mathbf{w}}$ ($\sum_{k=1}^{15} \hat{w}_k = 1.0$) and stored PostgreSQL/Redis profile weights remain unconstrained in $[0, 1]^{15}$.
   - Query 2: `"ارزون‌ترین آیفون ۱۶ در کل تهران"` $\rightarrow$ Verify `w_price` dominates even for stores 15 km away.
3. **Scenario C — Strict Stock (`offers.csv`) vs. Category Fallback (`shops.category_names`) (`US2`)**:
   - Search a specific stocked model $\rightarrow$ Verify all returned stores have `is_category_fallback = false` and exact `offers.price_toman`.
   - Search an unstocked niche item $\rightarrow$ Verify fallback stores display the amber badge `"پیشنهاد بر اساس دسته‌بندی فروشگاه (نیاز به استعلام تلفنی موجودی)"`.
4. **Scenario D — Indoor Mall Micro-Navigation & 1-Tap Fallback Rescue (`US4`)**:
   - Open `ShoppingCompanionModal.tsx` on a store inside `پاساژ علاءالدین` or `مجتمع تجاری نور تهران`.
   - Verify extracted badges: `پاساژ` / `طبقه` / `واحد` + `last_price_changed_at` freshness pill.
   - Click **"مغازه بسته بود / موجود نداشت — جایگزین فوری"** $\rightarrow$ Verify `< 300 ms` switch to the next open store in the same mall or nearby street.
