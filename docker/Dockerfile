# syntax=docker/dockerfile:1

# --- Stage 1: build the React UI -------------------------------------------------------------
FROM node:24-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# vite.config.ts writes to ../folio/static, i.e. /folio/static in this stage
RUN npm run build

# --- Stage 2: Python runtime -----------------------------------------------------------------
FROM python:3.12-slim AS app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=0 \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    FOLIO_HOST=0.0.0.0

COPY --from=ghcr.io/astral-sh/uv:0.12.0 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

COPY folio ./folio
COPY migrations ./migrations
COPY --from=web /folio/static ./folio/static

# The build the System page shows (FR-SY-10); CI passes the git commit.
ARG FOLIO_VERSION=dev
ENV FOLIO_VERSION=${FOLIO_VERSION}

# /data holds the database and backups; the container root filesystem stays read-only.
RUN mkdir -p /data && chown 10001:10001 /data
VOLUME /data
USER 10001:10001

EXPOSE 8080
ENTRYPOINT ["python", "-m", "folio.cli"]
CMD ["web"]
