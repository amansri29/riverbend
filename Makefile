.PHONY: run stop logs test lint migrate seed samples fmt

run:            ## One-command local run: Postgres + Pub/Sub emulator + API + worker
	docker compose up --build

stop:
	docker compose down -v

logs:
	docker compose logs -f api worker

test:           ## Unit + DB tests (needs Postgres from `docker compose up postgres`)
	uv run pytest -q

lint:
	uv run ruff check . && uv run ruff format --check .

fmt:
	uv run ruff format . && uv run ruff check --fix .

migrate:        ## Apply SQL migrations + seed shops against MIGRATION_DATABASE_URL
	uv run python scripts/migrate.py

samples:        ## Send the 40 sample messages, wait, send scripted replies, print the results table
	uv run python scripts/run_samples.py
