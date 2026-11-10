.PHONY: check backend-check web-check eval api web compose-smoke

check: backend-check eval web-check

backend-check:
	uv run --locked ruff check src tests evals deploy
	uv run --locked pytest -q

eval:
	uv run --locked python evals/run.py

web-check:
	cd web && npm ci --no-audit --no-fund && npm run build

api:
	uv run --locked uvicorn experiment_pilot.api:app --host 127.0.0.1 --port 8000

web:
	cd web && npm run dev

compose-smoke:
	docker compose up --build --wait
	uv run --locked python deploy/compose_smoke.py

.PHONY: production-smoke
production-smoke:
	sh deploy/check_production.sh
