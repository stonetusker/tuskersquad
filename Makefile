# --------------------------------------------------------
#  TuskerSquad - Makefile
#  Run from the project root directory.
# --------------------------------------------------------

COMPOSE = docker compose -f infra/docker-compose.yml --env-file infra/.env

.PHONY: up down restart build logs logs-api logs-dash logs-frontend \
        health ps env setup \
        demo-security demo-pricing demo-latency demo-all demo-clean

# -- Lifecycle ---------------------------------------------------------
up:
	@[ -f infra/.env ] || (echo "infra/.env not found - copying from .env.example" && cp infra/.env.example infra/.env)
	$(COMPOSE) up --build -d
	@echo ""
	@echo "TuskerSquad is running:"
	@echo "  UI       http://localhost:5173"
	@echo "  Demo App http://localhost:8080"
	@echo "  Gitea    http://localhost:3000"
	@echo "  API Docs http://localhost:8000/docs"
	@echo ""
	@echo "Webhook is auto-registered by the gitea-setup container."
	@echo "Add GITEA_TOKEN to infra/.env then run: make restart"

# restart: bounces only the application services (langgraph, integration, dashboard,
# frontend, demo-backend, catalog, order, user, postgres).
# gitea and gitea-setup are intentionally excluded:
#   - gitea  data (repos, users, tokens) lives in the `gitea_data` named volume
#             and must NOT be wiped on a normal restart.
#   - gitea-setup is a one-shot init container; it must NOT be re-run on restart
#             because it would create a duplicate token and is a no-op anyway
#             (the repo already exists and all files are already uploaded).
restart:
	$(COMPOSE) restart postgres langgraph-api integration-service dashboard frontend \
	    demo-backend catalog-service order-service user-service
	@echo ""
	@echo "Application services restarted (Gitea and gitea-setup left untouched)."
	@echo "  UI       http://localhost:5173"
	@echo "  API Docs http://localhost:8000/docs"

# setup: first-time Gitea initialisation OR recovery after `make down -v`.
# Run this ONLY when the shopflow repo is missing from Gitea.
# It will create the repo, register the webhook, upload all source files,
# and print a fresh GITEA_TOKEN to copy into infra/.env.
setup:
	@echo "Re-running Gitea setup (creates repo + uploads source if missing)..."
	$(COMPOSE) rm -f gitea-setup 2>/dev/null || true
	$(COMPOSE) up --build -d gitea-setup
	@echo "Done. Check logs: docker logs tuskersquad-gitea-setup"

down:
	$(COMPOSE) down

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

# -- Health check ------------------------------------------------------
health:
	@echo "-- Checking service health ----------------------"
	@curl -sf http://localhost:8000/api/health | python3 -m json.tool | head -3 \
	  && echo "  langgraph-api  ✅" || echo "  langgraph-api  ❌"
	@curl -sf http://localhost:8501/health    | python3 -m json.tool | head -3 \
	  && echo "  dashboard      ✅" || echo "  dashboard      ❌"
	@curl -sf http://localhost:8001/health    | python3 -m json.tool | head -3 \
	  && echo "  integration    ✅" || echo "  integration    ❌"
	@curl -sf http://localhost:8080/health    | python3 -m json.tool | head -3 \
	  && echo "  demo-backend   ✅" || echo "  demo-backend   ❌"

env:
	@echo "-- Current infra/.env ---------------------------"
	@grep -v '^#' infra/.env 2>/dev/null | grep -v '^$$' \
	  | sed 's/\(PASSWORD\|TOKEN\|SECRET\)=.*/\1=***/'

# -- Demo bug shortcuts ------------------------------------------------
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
