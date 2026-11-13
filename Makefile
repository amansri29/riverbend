.PHONY: run stop logs logs-all psql psql-app test coverage lint migrate samples fmt note

run:            ## One-command local run: Postgres + Pub/Sub emulator + API + worker
	docker compose up --build

stop:
	docker compose down -v

logs:           ## Follow the API and worker (one line per stage; grep 'message=<id>' to follow one message)
	docker compose logs -f api worker

logs-all:       ## Everything, including the Pub/Sub emulator and Postgres (noisy; for delivery problems)
	docker compose logs -f

psql:           ## Postgres console in the Compose stack as the owner (sees every shop)
	docker compose exec postgres psql -U postgres -d riverbend

psql-app:       ## Same, as the app role: row-level security applies. Try: SET app.shop_id = 'rb-downtown';
	docker compose exec postgres psql -U riverbend_app -d riverbend

test:           ## Unit + DB tests (needs Postgres from `docker compose up postgres`)
	uv run pytest -q

coverage:       ## Tests with line coverage: summary in the terminal, details in htmlcov/index.html
	uv run pytest -q --cov=app --cov-report=term-missing:skip-covered --cov-report=html

lint:
	uv run ruff check . && uv run ruff format --check .

fmt:
	uv run ruff format . && uv run ruff check --fix .

migrate:        ## Apply SQL migrations + seed shops against MIGRATION_DATABASE_URL
	uv run python scripts/migrate.py

samples:        ## Send the 40 sample messages, wait, send scripted replies, print the results table
	uv run python scripts/run_samples.py

note:  ## render docs/architecture.md to PDF and fail if it exceeds two pages
	uv run --with markdown --with pypdf python scripts/render_note.py
