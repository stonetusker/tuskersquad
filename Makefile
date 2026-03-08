# ═══════════════════════════════════════════════════════
#  TuskerSquad — Makefile
# ═══════════════════════════════════════════════════════

COMPOSE = docker compose -f infra/docker-compose.yml

.PHONY: up down restart build logs logs-api logs-dash logs-frontend \
        health env demo-security demo-pricing demo-latency demo-all demo-clean

up:
	$(COMPOSE) up --build -d
	@echo ""
	@echo "  ✅  TuskerSquad is running"
	@echo "  ──────────────────────────────────────────────"
	@echo "  🎨  UI          http://localhost:5173"
	@echo "  🛒  Demo App    http://localhost:8080"
	@echo "  📡  Gitea       http://localhost:3000"
	@echo "  📖  API Docs    http://localhost:8000/api/docs"
	@echo "  ──────────────────────────────────────────────"

down:
	$(COMPOSE) down

restart: down up

build:
	$(COMPOSE) build --no-cache

logs:
	$(COMPOSE) logs -f

logs-api:
	$(COMPOSE) logs -f langgraph-api

logs-dash:
	$(COMPOSE) logs -f dashboard

logs-frontend:
	$(COMPOSE) logs -f frontend

health:
	@echo "── Checking service health ──────────────────────"
	@curl -sf http://localhost:8000/api/health  | python3 -m json.tool --no-ensure-ascii | head -3 && echo "  langgraph-api  ✅" || echo "  langgraph-api  ❌"
	@curl -sf http://localhost:8501/health      | python3 -m json.tool --no-ensure-ascii | head -3 && echo "  dashboard      ✅" || echo "  dashboard      ❌"
	@curl -sf http://localhost:8001/health      | python3 -m json.tool --no-ensure-ascii | head -3 && echo "  integration    ✅" || echo "  integration    ❌"
	@curl -sf http://localhost:8080/health      | python3 -m json.tool --no-ensure-ascii | head -3 && echo "  demo-backend   ✅" || echo "  demo-backend   ❌"

env:
	@echo "── Current .env ─────────────────────────────────"
	@grep -v '^#' infra/.env | grep -v '^$$' | sed 's/PASSWORD=.*/PASSWORD=***/' | sed 's/TOKEN=.*/TOKEN=***/'

## ── Bug flag shortcuts ────────────────────────────────
demo-security:
	@echo "Enabling BUG_SECURITY on demo-backend…"
	$(COMPOSE) stop demo-backend
	BUG_SECURITY=true $(COMPOSE) up -d demo-backend

demo-pricing:
	@echo "Enabling BUG_PRICE on demo-backend…"
	$(COMPOSE) stop demo-backend
	BUG_PRICE=true $(COMPOSE) up -d demo-backend

demo-latency:
	@echo "Enabling BUG_SLOW on demo-backend…"
	$(COMPOSE) stop demo-backend
	BUG_SLOW=true $(COMPOSE) up -d demo-backend

demo-all:
	@echo "Enabling ALL bugs on demo-backend…"
	$(COMPOSE) stop demo-backend
	BUG_PRICE=true BUG_SECURITY=true BUG_SLOW=true $(COMPOSE) up -d demo-backend

demo-clean:
	@echo "Resetting demo-backend (no bugs)…"
	$(COMPOSE) stop demo-backend
	$(COMPOSE) up -d demo-backend
