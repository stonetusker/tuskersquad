# TuskerSquad User Manual

This document is a step-by-step user manual for running and presenting the TuskerSquad demonstration. It includes exact commands to run, validation checks, placeholder locations for screenshots, and a minute-by-minute presenter script for the 20-minute demo flow.

Files added/edited by this manual:
- `infra/docker-compose.yml` — compose stack used in demo
- `apps/frontend` — React + Vite dashboard UI
- `services/langgraph_api` — workflow orchestration & persistence
- `services/dashboard` — dashboard proxy used by the UI

---

## Before the demo (Prerequisites)

- Host: macOS (recommended MacBook M1/M2/M3). Install Docker Desktop (Compose v2) and optionally OrbStack.
- Install Ollama on host if you want to run large LLM models locally. Do NOT containerize Ollama for improved host performance.
- Ensure Node 20+ is available if you run the frontend outside Docker.
- Recommended: set a `GITEA_TOKEN` environment variable for PR comment posting.

Environment variables (examples):

```bash
export GITEA_TOKEN=ghp_exampletoken
export OLLAMA_URL=http://host.docker.internal:11434
```

Placeholders for screenshots used in this manual:
- `docs/screenshots/01-compose-up.png`
- `docs/screenshots/02-gitea-pr.png`
- `docs/screenshots/03-dashboard-list.png`
- `docs/screenshots/04-workflow-detail.png`
- `docs/screenshots/05-approve.png`

You can capture screenshots on macOS with:

```bash
screencapture -i docs/screenshots/03-dashboard-list.png
```

---

## Start the stack

From repository root:

```bash
docker compose -f infra/docker-compose.yml up --build
```

Services and default ports (compose):
- LangGraph API: http://localhost:8000 (API prefix `/api`)
- Integration service: http://localhost:8001
- Dashboard proxy: http://localhost:8501
- Frontend (Vite dev): http://localhost:5173
- Postgres: 5432
- Gitea: http://localhost:3000

Verify containers are running:

```bash
docker compose -f infra/docker-compose.yml ps
```

Expected output: containers `tuskersquad-langgraph`, `tuskersquad-dashboard`, `tuskersquad-integration`, `tuskersquad-frontend`, `tuskersquad-postgres`, `tuskersquad-gitea` are `Up`.

Capture screenshot: `docs/screenshots/01-compose-up.png`

Demo mode: if you want to run the frontend UI without the backend stack, start the frontend dev server and enable demo mode:

```bash
cd apps/frontend
npm install
VITE_USE_DEMO=true npm run dev
```

In demo mode the UI loads `public/demo_data.json` and simulates workflow lifecycle and approval actions.

---

## Create a demo PR (Gitea)

1. Open Gitea at http://localhost:3000 and sign in (the compose image is pre-configured with a demo admin; if not, create an account).
2. Create or fork the demo repo and open a Pull Request.

Capture screenshot: `docs/screenshots/02-gitea-pr.png`.

Note: If you prefer to simulate the webhook without Gitea UI, call the integration service directly:

```bash
curl -sS -X POST http://localhost:8001/webhook/simulate -H 'Content-Type: application/json' -d '{"repo":"tuskeradmin/demo-store","pr_number":42}'
```

---

## End-to-end flow (what happens)

1. Gitea webhook triggers the Integration Service.
2. Integration Service posts to LangGraph `/api/workflow/start` with `{repo, pr_number}`.
3. LangGraph persists a `WorkflowRun` in Postgres and registers a light-weight in-memory workflow state for fast inspection.
4. LangGraph starts deterministic orchestration:
   - **Code Review Phase**: planner → backend → frontend → security → sre
   - **Build Phase**: builder (clones PR code, builds Docker image)
   - **Deploy Phase**: deployer (creates ephemeral container)
   - **Test Phase**: tester (runs automated API and performance tests)
   - **Analysis Phase**: runtime_analyzer (analyzes logs and behavior)
   - **Log Analysis**: log_inspector (reads microservice logs)
   - **Correlation**: correlator (joins all findings into root cause chains)
   - **Validation**: challenger → qa_lead → judge
5. Each agent executes, emits logs and findings, then persists findings to `engineering_findings`.
5. If findings exist, LangGraph writes a governance record and sets the workflow status to `WAITING_HUMAN_APPROVAL`.
6. The Dashboard UI polls `services/dashboard` which proxies the DB-backed endpoints on LangGraph.
7. A human clicks `Approve` or `Reject` in the dashboard; LangGraph persists the governance decision and marks the workflow `COMPLETED`.
8. On approve, LangGraph attempts a best-effort PR comment to Gitea using `GITEA_TOKEN`. Failures do not block completion.

---

## Useful commands / checks during the demo

- List workflows (dashboard proxy):

```bash
curl -sS http://localhost:8501/api/ui/workflows | jq .
```

- Get workflow detail (dashboard proxy):

```bash
curl -sS http://localhost:8501/api/ui/workflow/<workflow_id> | jq .
```

- Get agents/findings/governance:

```bash
curl -sS http://localhost:8501/api/ui/workflow/<workflow_id>/agents | jq .
curl -sS http://localhost:8501/api/ui/workflow/<workflow_id>/findings | jq .
curl -sS http://localhost:8501/api/ui/workflow/<workflow_id>/governance | jq .
```

- Approve a workflow (dashboard proxy):

```bash
curl -sS -X POST http://localhost:8501/api/ui/workflow/<workflow_id>/approve | jq .
```

- Direct DB inspection (Postgres container):

```bash
docker exec -it tuskersquad-postgres psql -U tusker -d tuskersquad
# then inside psql
SELECT id, repository, pr_number, status, created_at FROM workflow_runs ORDER BY created_at DESC LIMIT 10;
SELECT id, agent, title, severity, created_at FROM engineering_findings ORDER BY created_at DESC LIMIT 10;
```

---

## Where to find artifacts

- Workflow runs: `services/langgraph_api/db/models.py` (`WorkflowRun` table)
- Findings: `engineering_findings` table
- Challenges: `finding_challenges` table
- Governance actions: `governance_actions` table
- Agent execution logs: `agent_execution_log` table

---

## Presenter script (20-minute demo)

Use this script verbatim or adapt to your style. Each bullet is a line to speak or an action to perform; timings are approximate.

0:00 - 0:30 — Setup intro
- "Hello — I'm going to show TuskerSquad, an AI‑assisted engineering governance platform. Our goal: demonstrate how AI agents assist engineering workflows while keeping humans in control."

0:30 - 2:00 — Show environment & compose
- Action: Show `docker ps` on-screen or the `01-compose-up.png` screenshot.
- Speak: "The demo runs locally with Postgres, LangGraph orchestration, a dashboard proxy, an integration webhook service, a local Gitea, and a Vite frontend. Ollama runs on the host for LLMs."

2:00 - 3:00 — Create PR in Gitea
- Action: Show `02-gitea-pr.png` or create a quick PR.
- Speak: "Developer creates a PR. A webhook is sent to TuskerSquad's integration service."

3:00 - 6:00 — Show integration -> LangGraph
- Action: Tail the `tuskersquad-integration` logs: `docker logs -f tuskersquad-integration` and point to the POST call to LangGraph.
- Speak: "Integration service receives the webhook and starts a workflow by calling LangGraph's API."

6:00 - 9:00 — Planner and agent assignment (live)
- Action: Switch to http://localhost:5173, open the workflow list (`03-dashboard-list.png`).
- Speak: "Planner assigns tasks to agents (backend, frontend, security, SRE). You'll see agent timeline update in real time."

9:00 - 12:00 — Agents run tests & post findings
- Action: Show `Findings` panel for a selected workflow (`04-workflow-detail.png`). Optionally tail `tuskersquad-langgraph` logs.
- Speak: "Agents run tests and post findings to the evidence store. Here are the persisted findings and their severity."

12:00 - 15:00 — Challenger & QA summary
- Action: Show a dispute (challenge) record in the findings or open `finding_challenges` in Postgres.
- Speak: "Challenger detects disagreement (e.g., backend says one thing, security another). QA Lead compiles a risk summary."

15:00 - 18:00 — Judge decision and wait for human
- Action: Show that Judge blocked deployment (workflow status `WAITING_HUMAN_APPROVAL`).
- Speak: "Judge recommended blocking. The workflow is waiting for human QA Lead approval."

18:00 - 19:30 — Human Approval
- Action: Click `Approve` in the UI or call the approve API.
- Speak: "QA Lead approves. LangGraph marks the workflow completed and posts a PR comment in Gitea (if GITEA_TOKEN is configured)."

19:30 - 20:00 — Wrap-up
- Speak: "That demonstrates end-to-end governance — LLM-assisted checks, recorded evidence, human oversight, and best-effort Git integration. Next steps: hook into CI and extend with real LLM prompts."

---

## Screenshots and artifacts (how to capture)

- Compose status: `docker compose -f infra/docker-compose.yml ps` → screenshot `docs/screenshots/01-compose-up.png`.
- Gitea PR: open browser → screenshot `docs/screenshots/02-gitea-pr.png`.
- Dashboard list/detail: open http://localhost:5173 → screenshot `docs/screenshots/03-dashboard-list.png` and `docs/screenshots/04-workflow-detail.png`.
- Approval action: click approve → screenshot `docs/screenshots/05-approve.png`.

Command to create screenshots on macOS:

```bash
mkdir -p docs/screenshots
screencapture -i docs/screenshots/03-dashboard-list.png
```

---

## Recovery & troubleshooting notes for presenters

- If a service is not responding, check its logs:
  - `docker logs -f tuskersquad-langgraph`
  - `docker logs -f tuskersquad-dashboard`
  - `docker logs -f tuskersquad-frontend`
- If DB is empty or migrations failed, restart stack and watch `langgraph` startup logs — `init_db()` runs at startup.
- If Gitea comments do not appear, ensure `GITEA_TOKEN` is set and the token has repo scope.

---

## Next steps (optional automation)

I can add:
- Playwright tests that open the UI and click through the workflow lifecycle automatically.
- A `docs/PRESENTER_SCRIPT.md` with copy-ready lines and expected visual cues per step.
- GitHub Actions CI that boots the compose stack and runs the Week‑6 E2E tests.

---

End of manual.
