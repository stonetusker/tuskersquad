build:
	docker compose -f infra/docker-compose.yml up --build -d

down:
	docker compose -f infra/docker-compose.yml down

shell:
	docker exec -it tuskersquad-langgraph bash

ollama-test:
	docker exec -it tuskersquad-langgraph python scripts/check_ollama.py

logs:
	docker logs -f tuskersquad-langgraph

logs-all:
	docker compose -f infra/docker-compose.yml logs -f

ps:
	docker compose -f infra/docker-compose.yml ps

test-unit:
	PYTHONPATH=$(PWD):$(PWD)/services/langgraph_api pytest -q tests/unit

test-e2e:
	pytest -q tests/integration/test_week6_e2e.py

demo-mode:
	cd apps/frontend && VITE_USE_DEMO=true npm run dev

warm-models:
	python scripts/warm_models.py

demo-bugs-on:
	BUG_PRICE=true BUG_SLOW=true BUG_SECURITY=true docker compose -f infra/docker-compose.yml up -d demo-backend

demo-bugs-off:
	docker compose -f infra/docker-compose.yml up -d demo-backend
