FROM ghcr.io/astral-sh/uv:0.11.8 AS uv

FROM python:3.13-slim-bookworm
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra observability --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --extra observability --no-editable \
    && useradd --create-home --shell /usr/sbin/nologin pilot \
    && mkdir -p /app/.state \
    && chown pilot:pilot /app/.state
USER pilot
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "experiment_pilot.api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--limit-concurrency", "80", "--timeout-graceful-shutdown", "30"]
