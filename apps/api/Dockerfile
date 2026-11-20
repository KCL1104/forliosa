# Forliosa API / worker image (Railway). Build context: apps/api
FROM python:3.13-slim

# pg_dump / pg_restore for the worker's nightly backup (forliosa.backup). The client must be at least the server's
# major version (Railway Postgres 18); Debian's own is older, so it comes from the PostgreSQL apt repository (PGDG).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc https://www.postgresql.org/media/keys/ACCC4CF8.asc \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-18 \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

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
# --timeout-graceful-shutdown: how long a deploy waits for requests in flight. Open realtime streams (GET /api/v1/events)
# end at the SIGTERM itself with bye{rotate} (forliosa.api.app.close_streams_on_signal); the browsers reconnect to the
# new process.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn forliosa.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*' --timeout-graceful-shutdown 10"]
