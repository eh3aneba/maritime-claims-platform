.PHONY: up down logs api-check test migration-sql migrate pilot-mt-orion

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


pilot-mt-orion:
	cd apps/api && pytest -q tests/test_mt_orion_end_to_end_pilot.py
