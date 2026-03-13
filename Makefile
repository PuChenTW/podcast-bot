run:
	uv run python main.py

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
