FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY alembic ./alembic
COPY scripts ./scripts
COPY config/jev/question-definitions.v1.yaml ./config/jev/question-definitions.v1.yaml
COPY config/jev/locks/next-action.typesafe-jev.v2.lock.json ./config/jev/locks/next-action.typesafe-jev.v2.lock.json
COPY config/jev/locks/next-action.typesafe-jev.v2.lock.json.meta.json ./config/jev/locks/next-action.typesafe-jev.v2.lock.json.meta.json
COPY alembic.ini ./
COPY docker-entrypoint.sh ./

RUN apt-get update \
    && apt-get install --no-install-recommends -y git poppler-utils \
    && pip install --no-cache-dir uv==0.11.28 \
    && echo "[FIX] Installing pinned VCS dependency jevcal for the Jev runtime extra" \
    && uv sync --frozen --no-dev --extra jev \
    && echo "[FIX] Pinned Jev runtime dependencies installed" \
    && apt-get purge --auto-remove -y git \
    && ! command -v git \
    && rm -rf /var/lib/apt/lists/* \
    && chmod +x /app/docker-entrypoint.sh

ENV PATH="/app/.venv/bin:${PATH}"

EXPOSE 8020
ENTRYPOINT ["/app/docker-entrypoint.sh"]
