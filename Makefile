run:
	uv run python main.py

migrate-up:
	uv run python -m migrate up

migrate-down:
	uv run python -m migrate down $(version)

migrate-status:
	uv run python -m migrate status

test:
	uv run pytest tests/ -v

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
