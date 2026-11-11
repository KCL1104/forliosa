# Forliosa API / worker image (Railway). Build context: apps/api
FROM python:3.13-slim

RUN pip install --no-cache-dir uv==0.11.32

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies first (cached layer), then the project itself.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 forliosa \
    && mkdir -p /app/var/cache \
    && chown -R forliosa:forliosa /app/var
USER forliosa

ENV PATH="/app/.venv/bin:$PATH" \
    FORLIOSA_ENV=prod \
    PORT=8000
EXPOSE 8000

# API: migrate, then serve on $PORT. The worker service overrides this with `python -m forliosa.worker`.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn forliosa.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
