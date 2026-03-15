.PHONY: run web-run migrate-up migrate-down migrate-status test lint format docker-build docker-up docker-down docker-logs docker-restart

run:
	uv run python main.py

web-run:
	uv run uvicorn web_main:app --reload --port 8000

migrate-up:
	uv run python -m migrate up

migrate-down:
	uv run python -m migrate down $(version)

migrate-status:
	uv run python -m migrate status

test:
	uv run pytest tests/ -v

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
