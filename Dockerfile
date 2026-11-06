# ==============================================================================
# Stage 1: Build React 19 + Vite + Tailwind v4 + Leaflet RTL Frontend (`UI_Template`)
# ==============================================================================
FROM node:22-alpine AS frontend-builder
WORKDIR /build/UI_Template

COPY UI_Template/package.json UI_Template/package-lock.json* ./
RUN npm install --legacy-peer-deps

COPY UI_Template/ ./
RUN npm run build

# ==============================================================================
# Stage 2: FastAPI + asyncpg + pgvector + Redis + Jev System One Runtime
# ==============================================================================
FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY backend/ ./backend/
COPY .env.example ./.env.example
COPY --from=frontend-builder /build/UI_Template/dist ./UI_Template/dist

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health')" || exit 1

CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
