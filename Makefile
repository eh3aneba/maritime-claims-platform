.PHONY: up down logs api-check

up:
	docker compose up --build

down:
	docker compose down

logs:
	docker compose logs -f

api-check:
	cd apps/api && python -m compileall app
