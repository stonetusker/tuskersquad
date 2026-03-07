 # TuskerSquad — AI Engineering Governance Platform

 This repository contains TuskerSquad: a multi-service sample platform demonstrating
 multi-agent code review workflows, persistence, a dashboard for human approval,
 and best-effort PR integration with Gitea. The stack is implemented with FastAPI
 services, PostgreSQL persistence, and a React + Vite dashboard.

 Quick overview
 - `services/langgraph_api` — core workflow orchestration and persistence (FastAPI)
 - `services/dashboard` — lightweight proxy API used by the frontend (FastAPI)
 - `services/integration_service` — receives external events and starts workflows
 - `apps/frontend` — React + Vite dashboard UI (development server runs on port 5173)
 - `infra/docker-compose.yml` — development compose file to run the full stack
 - `services/langgraph_api/db` — SQLAlchemy models and DB initialization

 Prerequisites
 - Docker & Docker Compose (v2), Node.js 20+ (only needed locally if you run the frontend outside compose)
 - Optionally a local Gitea instance if you want PR comments (compose includes a Gitea service)

 Environment variables (compose uses defaults but you can override):
 - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_HOST`, `POSTGRES_PORT`
 - `OLLAMA_URL` — LLM endpoint (not required for Week‑6 deterministic flow)
 - `GITEA_URL`, `GITEA_TOKEN` — used for posting PR comments (best-effort; workflow continues if posting fails)

 Development: bring up the full stack with Docker Compose

 1) Build and start the stack (LangGraph API, Dashboard, Integration service, Postgres, Gitea, Frontend dev server):

 ```bash
 docker compose -f infra/docker-compose.yml up --build
 ```

 2) Services and ports (defaults):
 - LangGraph API: http://localhost:8000 (API prefix `/api`)
 - Integration service: http://localhost:8001
 - Dashboard proxy: http://localhost:8501
 - Frontend (Vite dev): http://localhost:5173
 - Postgres: 5432
 - Gitea: http://localhost:3000

 How the system works (high level)
 - A workflow run is started by calling the LangGraph API: POST /api/workflow/start with JSON `{ "repo": "owner/repo", "pr_number": 42 }`.
 - LangGraph creates a `WorkflowRun` in Postgres and registers an in-memory status object in the workflow registry.
 - A deterministic multi-agent orchestration (planner → backend → frontend → security → sre → challenger → judge) executes in a background thread. Agents produce findings which are persisted to the database.
 - When agents surface issues the workflow moves to `WAITING_HUMAN_APPROVAL`. The dashboard queries LangGraph (via `services/dashboard`) to present workflows, agent timelines, findings and governance actions.
 - A human can `approve` or `reject` via the dashboard API which updates governance records and finalizes the workflow. On approval, the system attempts a best-effort PR comment to Gitea using `GITEA_URL`/`GITEA_TOKEN`.

 Useful API endpoints
 - Start workflow: POST http://localhost:8000/api/workflow/start
	 - Body: `{ "repo": "owner/repo", "pr_number": 42 }` (Pydantic validated)
 - List workflows (in-memory): GET http://localhost:8000/api/workflows
 - List workflows (DB-backed, used by dashboard): GET http://localhost:8000/api/api/workflows
 - Get workflow (DB): GET http://localhost:8000/api/api/workflow/{workflow_id}
 - Dashboard proxy endpoints (use these from the UI):
	 - GET /api/ui/workflows — list workflows
	 - GET /api/ui/workflow/{workflow_id} — workflow details
	 - GET /api/ui/workflow/{workflow_id}/agents — agent timeline
	 - GET /api/ui/workflow/{workflow_id}/findings — findings list
	 - GET /api/ui/workflow/{workflow_id}/governance — governance records
	 - POST /api/ui/workflow/{workflow_id}/approve — approve workflow
	 - POST /api/ui/workflow/{workflow_id}/reject — reject workflow

 Frontend development
 - The compose file starts a `frontend` service (Vite) mounted to the repo for live edits. If you prefer to run locally outside Docker:

 ```bash
 cd apps/frontend
 npm install
 npm run dev
 ```

 The frontend reads `VITE_DASH_URL` (defaults to http://localhost:8501) to call the dashboard proxy.

 Running tests
 - Unit tests and integration tests are included under `tests/`.
 - Run unit tests:
 ```bash
 PYTHONPATH=$PWD:$PWD/services/langgraph_api pytest -q tests/unit
 ```
 - Run the Week‑6 E2E integration test:
 ```bash
 pytest -q tests/integration/test_week6_e2e.py -q
 ```

 Troubleshooting
 - If containers fail to start due to database migration or connection errors, check Postgres logs and ensure the DB env vars match in the compose file.
 - If Vite errors with Node engine version, ensure the `frontend` service uses Node 20 (the compose file sets `node:20`) or update your local Node to 20+.
 - If the dashboard returns 502 when proxying, check that `LANGGRAPH_URL` in `services/dashboard/main.py` points to the correct LangGraph address (defaults to `http://tuskersquad-langgraph:8000` inside compose).
 - Gitea posting is best-effort: missing `GITEA_TOKEN` will skip posting but will not block workflow completion.

 Development notes & next steps
 - The deterministic SimpleGraph runner produces synthetic findings for Week‑6; swap to real LLM calls in `core/llm_client.py` if you want to test LLM agents.
 - Consider adding healthchecks and Compose `depends_on` health conditions for more deterministic startup ordering.
 - Add CI (GitHub Actions) to run unit and integration tests and optionally spin up the stack for E2E validation.

Contact / contribution
- This project is intended as an educational sample. Contributions welcome via PRs — please run tests locally and document changes.

---

## User Manual

This section describes how to run the demo, the demonstration story, and typical user actions during a live demo.

1) Prepare the host
 - Install Docker Desktop (or OrbStack) and ensure Docker Compose v2 is available.
 - Install Ollama on the macOS host (recommended for model hosting). Configure `OLLAMA_URL` as `http://host.docker.internal:11434` if running locally.

2) Start the stack

 ```bash
 docker compose -f infra/docker-compose.yml up --build
 ```

 Wait until the following services are listed as `Up` in `docker ps`:
 - tuskersquad-postgres (Postgres)
 - tuskersquad-gitea (Gitea)
 - tuskersquad-langgraph (LangGraph API)
 - tuskersquad-dashboard (Dashboard proxy)
 - tuskersquad-integration (Integration service)
 - tuskersquad-frontend (Vite dev server)

3) Demo flow (operator steps)
 - Developer creates a PR in Gitea (or create a test PR in the demo repo).
 - Integration service receives the webhook and posts to LangGraph: POST /api/workflow/start.
 - LangGraph persists a `WorkflowRun` and starts deterministic agent execution.
 - Open the UI at http://localhost:5173 (frontend) to monitor activity.
 - Select a workflow in the sidebar to inspect `agents`, `findings`, and `governance`.
 - When the workflow reaches `WAITING_HUMAN_APPROVAL`, click `Approve` or `Reject` in the UI. This calls dashboard proxy `/api/ui/workflow/{id}/approve`.
 - On approve, LangGraph will mark the workflow `COMPLETED` and attempt a best-effort PR comment to Gitea (requires `GITEA_TOKEN`).

4) Inspect data directly (optional)
 - Connect to postgres and query tables for `workflow_runs`, `engineering_findings`, `finding_challenges`, and `governance_actions`.

5) Typical demo script (20 minutes):
 - 0:00–2:00: Create PR and show webhook arriving in Integration service.
 - 2:00–6:00: Planner agent assigns work; show agent timeline.
 - 6:00–12:00: Backend/frontend/security/SRE agents run tests and post findings.
 - 12:00–15:00: Challenger disputes a finding; QA Lead compiles risk summary.
 - 15:00–18:00: Judge blocks deployment; request human QA review.
 - 18:00–20:00: QA Lead approves via dashboard; show PR comment in Gitea (if token configured).

6) Troubleshooting quick list
 - Vite parse errors: ensure Node 20+ is used by the `frontend` service. The compose file uses `node:20` already.
 - DB connection errors: check `tuskersquad-postgres` logs and `POSTGRES_*` env in `infra/docker-compose.yml`.
 - Dashboard 502: confirm `LANGGRAPH_URL` in `services/dashboard/main.py` or env points to LangGraph.

---

## Project Objective & Implementation Checklist

The following map shows where each objective is implemented in the codebase. Use this to validate demo completeness.

- Sprint planning (Planner Agent): implemented in `services/langgraph_api/workflows/graph_builder.py` and `workflows/pr_review_workflow.py`.
- Engineering task assignment: `planner` synthetic agent in the deterministic graph.
- Backend testing (pytest): Backend agent simulates or invokes test runner in `agents` codepath of the workflow runner.
- UI testing (Playwright): Frontend agent placeholder (see `apps/frontend` for the Playwright harness setup).
- Security validation: `security` agent in the deterministic graph produces findings and evidence persisted to `engineering_findings`.
- Performance evaluation (SRE): `sre` agent uses simulated k6-like checks in the workflow runner.
- Peer disagreement resolution (Challenger): `challenger` agent in the workflow graph and persistence in `finding_challenges`.
- Human approval governance: Dashboard UI + LangGraph endpoints `/workflow/{id}/approve` and `/workflow/{id}/reject`.
- CI/CD release enforcement: Demonstrated via `judge` agent decision recorded in `governance_actions`; integration to CI pipelines is a recommended extension.

---

## Where to look in the code (quick links)
- Core orchestration: services/langgraph_api/workflows/pr_review_workflow.py
- API routes: services/langgraph_api/api/workflow_routes.py
- DB models: services/langgraph_api/db/models.py
- Dashboard proxy: services/dashboard/main.py
- Integration webhook: services/integration_service/main.py
- Frontend: apps/frontend/src
- Compose and infra: infra/docker-compose.yml and infra/Dockerfile.langgraph

---

If you'd like, I can also:
- Add a dedicated `docs/USER_MANUAL.md` file with step-by-step screenshots and a presenter script.
- Add Playwright tests that click through the UI to validate the full workflow automatically.
- Create a CI workflow that spins up the compose stack and runs the Week‑6 E2E test.

