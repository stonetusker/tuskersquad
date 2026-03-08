# TuskerSquad Makefile
# =====================
# Run from the project root (one level above infra/)

COMPOSE = docker compose -f infra/docker-compose.yml

.PHONY: up down restart clean logs ps build demo-bugs-on demo-bugs-off fresh

## Start all services (build if needed)
up:
	$(COMPOSE) up --build -d

## Attach to logs
logs:
	$(COMPOSE) logs -f

## Logs for a specific service: make logs-svc SVC=langgraph-api
logs-svc:
	$(COMPOSE) logs -f $(SVC)

## Show running containers
ps:
	$(COMPOSE) ps

## Stop all services (keep volumes)
down:
	$(COMPOSE) down

## Stop all services AND remove volumes (full reset — re-creates DB on next up)
clean:
	@echo "WARNING: This removes all data volumes including the database!"
	$(COMPOSE) down -v --remove-orphans

## Full clean rebuild: wipe volumes, rebuild images, start fresh
fresh: clean
	$(COMPOSE) up --build -d
	@echo "Fresh start complete — services starting at:"
	@echo "  Frontend:    http://localhost:5173"
	@echo "  Dashboard:   http://localhost:8501"
	@echo "  LangGraph:   http://localhost:8000"
	@echo "  Integration: http://localhost:8001"

## Enable demo bugs
demo-bugs-on:
	BUG_PRICE=true BUG_SLOW=true BUG_SECURITY=true $(COMPOSE) up -d demo-backend

## Disable demo bugs
demo-bugs-off:
	BUG_PRICE=false BUG_SLOW=false BUG_SECURITY=false $(COMPOSE) up -d demo-backend

## Restart just the langgraph service
restart-api:
	$(COMPOSE) restart langgraph-api

## Restart just the dashboard
restart-dash:
	$(COMPOSE) restart dashboard

## Restart just the demo backend
restart-demo:
	$(COMPOSE) restart demo-backend

## View logs for all backend services
logs-all:
	$(COMPOSE) logs -f langgraph-api dashboard integration-service demo-backend

## Run unit tests (outside Docker)
test-unit:
	PYTHONPATH=. pytest tests/unit/ -v

## Run integration tests (outside Docker, services must be running)
test-integration:
	PYTHONPATH=. pytest tests/integration/ -v
