.PHONY: up down logs api-check test migration-sql migrate

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

api-check:
	cd apps/api && python -m compileall app alembic

test:
	cd apps/api && pytest

migration-sql:
	cd apps/api && alembic upgrade head --sql

migrate:
	docker compose exec api alembic upgrade head
