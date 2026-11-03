FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /uvx /bin/
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY app ./app
COPY scripts ./scripts
COPY migrations ./migrations
COPY catalog ./catalog
COPY samples ./samples
RUN uv sync --frozen --no-dev
ENV PATH="/srv/.venv/bin:$PATH"
EXPOSE 8080 8081
# One image, two entrypoints: see docker-compose.yml and infra/terraform.
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8080"]
