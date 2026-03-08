# ═══════════════════════════════════════════════════════════════════════════
# TuskerSquad — Stonetusker Systems  ·  Makefile
# ═══════════════════════════════════════════════════════════════════════════

COMPOSE = docker compose -f infra/docker-compose.yml
ENV_FILE = infra/.env

.PHONY: help up fresh clean stop logs health simulate approve reject \
        demo-security demo-latency demo-pricing demo-all demo-clean

help:
	@echo ""
	@echo "  TuskerSquad — Stonetusker Systems"
	@echo "  ────────────────────────────────────"
	@echo "  make up             Start all services (build if needed)"
	@echo "  make fresh          Clean volumes + full rebuild + start"
	@echo "  make stop           Stop all services"
	@echo "  make clean          Stop and remove all volumes"
	@echo "  make logs           Tail langgraph-api logs"
	@echo "  make logs-all       Tail all service logs"
	@echo "  make health         Check all service health endpoints"
	@echo ""
	@echo "  make simulate       Trigger a demo workflow (no Gitea needed)"
	@echo "  make demo-security  Enable BUG_SECURITY and trigger"
	@echo "  make demo-latency   Enable BUG_SLOW and trigger"
	@echo "  make demo-pricing   Enable BUG_PRICE and trigger"
	@echo "  make demo-all       Enable all bugs and trigger"
	@echo "  make demo-clean     Disable all bugs"
	@echo ""
	@echo "  Auto-merge: set AUTO_MERGE_ON_APPROVE=true in infra/.env"
	@echo "  Deploy:     set DEPLOY_ON_MERGE=true in infra/.env"
	@echo ""

# ── Start / Stop ────────────────────────────────────────────────────────────
up:
	@if [ -f $(ENV_FILE) ]; then \
		$(COMPOSE) --env-file $(ENV_FILE) up --build; \
	else \
		$(COMPOSE) up --build; \
	fi

fresh:
	@echo "🧹 Clean start (removing volumes)…"
	$(COMPOSE) down -v --remove-orphans 2>/dev/null || true
	@if [ -f $(ENV_FILE) ]; then \
		$(COMPOSE) --env-file $(ENV_FILE) up --build; \
	else \
		$(COMPOSE) up --build; \
	fi

stop:
	$(COMPOSE) stop

clean:
	$(COMPOSE) down -v --remove-orphans

# ── Logs ────────────────────────────────────────────────────────────────────
logs:
	$(COMPOSE) logs -f langgraph-api

logs-all:
	$(COMPOSE) logs -f

logs-api:
	$(COMPOSE) logs -f langgraph-api

logs-dash:
	$(COMPOSE) logs -f dashboard

logs-frontend:
	$(COMPOSE) logs -f frontend

# ── Health ──────────────────────────────────────────────────────────────────
health:
	@echo "── LangGraph API ────────────────────"
	@curl -sf http://localhost:8000/api/health && echo " ✅" || echo " ❌"
	@echo "── Demo Backend ─────────────────────"
	@curl -sf http://localhost:8080/health && echo " ✅" || echo " ❌"
	@echo "── Integration Service ──────────────"
	@curl -sf http://localhost:8001/health && echo " ✅" || echo " ❌"
	@echo "── Dashboard ────────────────────────"
	@curl -sf http://localhost:8501/api/ui/workflows > /dev/null && echo " ✅" || echo " ❌"

# ── Demo triggers ────────────────────────────────────────────────────────────
simulate:
	@echo "🚀 Triggering demo workflow…"
	@curl -sf -X POST http://localhost:8001/webhook/simulate \
	     -H 'Content-Type: application/json' \
	     -d '{"repo":"tuskeradmin/demo-store","pr_number":42}' | python3 -m json.tool

demo-security:
	@echo "🔐 Enabling BUG_SECURITY…"
	@BUG_SECURITY=true $(COMPOSE) up -d demo-backend
	@sleep 3
	@$(MAKE) simulate

demo-latency:
	@echo "📡 Enabling BUG_SLOW…"
	@BUG_SLOW=true $(COMPOSE) up -d demo-backend
	@sleep 3
	@$(MAKE) simulate

demo-pricing:
	@echo "💰 Enabling BUG_PRICE…"
	@BUG_PRICE=true $(COMPOSE) up -d demo-backend
	@sleep 3
	@$(MAKE) simulate

demo-all:
	@echo "💥 Enabling all bugs…"
	@BUG_PRICE=true BUG_SECURITY=true BUG_SLOW=true $(COMPOSE) up -d demo-backend
	@sleep 3
	@$(MAKE) simulate

demo-clean:
	@echo "🧹 Disabling all bugs…"
	@$(COMPOSE) up -d demo-backend

# ── Env setup ───────────────────────────────────────────────────────────────
env:
	@if [ ! -f $(ENV_FILE) ]; then \
		cp infra/.env.example $(ENV_FILE); \
		echo "Created $(ENV_FILE) — edit it and set AUTO_MERGE_ON_APPROVE=true to enable auto-merge"; \
	else \
		echo "$(ENV_FILE) already exists"; \
	fi
