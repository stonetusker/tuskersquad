# ════════════════════════════════════════════════════════
#  TuskerSquad — Makefile
#  Run from the project root directory.
# ════════════════════════════════════════════════════════

COMPOSE = docker compose -f infra/docker-compose.yml --env-file infra/.env

.PHONY: up down restart build logs logs-api logs-dash logs-frontend \
        health ps env \
        demo-security demo-pricing demo-latency demo-all demo-clean

# ── Lifecycle ─────────────────────────────────────────────────────────
up:
	@[ -f infra/.env ] || (echo "⚠  infra/.env not found — copying from .env.example" && cp infra/.env.example infra/.env)
	$(COMPOSE) up --build -d
	@echo ""
	@echo "  ✅  TuskerSquad is running"
	@echo "  ────────────────────────────────────────────"
	@echo "  🎨  UI          http://localhost:5173"
	@echo "  🛒  Demo App    http://localhost:8080"
	@echo "  📡  Gitea       http://localhost:3000"
	@echo "  📖  API Docs    http://localhost:8000/docs"
	@echo "  ────────────────────────────────────────────"

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

ps:
	$(COMPOSE) ps

# ── Health check ──────────────────────────────────────────────────────
health:
	@echo "── Checking service health ──────────────────────"
	@curl -sf http://localhost:8000/api/health | python3 -m json.tool | head -3 \
	  && echo "  langgraph-api  ✅" || echo "  langgraph-api  ❌"
	@curl -sf http://localhost:8501/health    | python3 -m json.tool | head -3 \
	  && echo "  dashboard      ✅" || echo "  dashboard      ❌"
	@curl -sf http://localhost:8001/health    | python3 -m json.tool | head -3 \
	  && echo "  integration    ✅" || echo "  integration    ❌"
	@curl -sf http://localhost:8080/health    | python3 -m json.tool | head -3 \
	  && echo "  demo-backend   ✅" || echo "  demo-backend   ❌"

env:
	@echo "── Current infra/.env ───────────────────────────"
	@grep -v '^#' infra/.env 2>/dev/null | grep -v '^$$' \
	  | sed 's/\(PASSWORD\|TOKEN\|SECRET\)=.*/\1=***/'

# ── Demo bug shortcuts ────────────────────────────────────────────────
demo-security:
	$(COMPOSE) stop demo-backend
	BUG_SECURITY=true $(COMPOSE) up -d demo-backend

demo-pricing:
	$(COMPOSE) stop demo-backend
	BUG_PRICE=true $(COMPOSE) up -d demo-backend

demo-latency:
	$(COMPOSE) stop demo-backend
	BUG_SLOW=true $(COMPOSE) up -d demo-backend

demo-all:
	$(COMPOSE) stop demo-backend
	BUG_PRICE=true BUG_SECURITY=true BUG_SLOW=true $(COMPOSE) up -d demo-backend

demo-clean:
	$(COMPOSE) stop demo-backend
	$(COMPOSE) up -d demo-backend
