.PHONY: run web-run migrate-up migrate-down migrate-status migrate-sqlite test lint format docker-build docker-up docker-down docker-logs docker-restart

bot-run:
	uv run python bot_main.py

web-run:
	uv run uvicorn web_main:app --reload --port 8000

migrate-up:
	uv run python -m migrate up

migrate-down:
	uv run python -m migrate down $(version)

migrate-status:
	uv run python -m migrate status

migrate-sqlite:
	uv run python scripts/migrate_sqlite_to_postgres.py --sqlite $(sqlite) --postgres $(postgres)

test:
	uv run pytest tests/ -v -n auto

lint:
	uv run ruff check .

format:
	uv run ruff format .

docker-build:
	docker compose build

docker-up:
	docker compose up -d

docker-down:
	docker compose down

docker-logs:
	docker compose logs -f

docker-restart:
	docker compose restart

sync:
	uv sync --all-extras
