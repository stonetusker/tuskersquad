# TuskerSquad — Stonetusker Systems
### Agentic AI PR Governance Platform

> **13 AI agents. One human decision. Automatic build, deploy, test, and merge.**

TuskerSquad runs an autonomous 13-agent pipeline over every Pull Request:
**Planner → Backend → Frontend → Security → SRE → Builder → Deployer → Tester → Runtime Analyzer → Log Inspector → Correlator → Challenger → QA Lead → Judge**

When the Judge flags `REVIEW_REQUIRED`, a human approves or rejects from the dashboard.
On **Approve**, TuskerSquad can **automatically merge the PR** and **trigger your deploy pipeline** — zero manual steps.

---

## ✨ What's New — Build, Deploy, Test & Runtime Analysis

| Feature | How |
|---|---|
| **Automatic Build** | Builder agent clones PR code and builds Docker images |
| **Ephemeral Deploy** | Deployer creates isolated containers for each PR |
| **Automated Testing** | Tester runs API, performance, and health tests |
| **Runtime Analysis** | Runtime Analyzer examines logs, performance, and behavior |
| **Code + Runtime Validation** | Combined static analysis + live testing before approval |
| **Auto-Merge on Approve** | Calls the Gitea Merge API immediately after human APPROVE |
| **Merge style** | `merge` / `rebase` / `squash` — configurable per deployment |
| **Auto-Deploy after Merge** | Dispatches a Gitea Actions `workflow_dispatch` event |
| **PR Labels** | Sets `tuskersquad:approved` / `tuskersquad:rejected` / `tuskersquad:deployed` |
| **Rich PR comment** | Posts QA summary, findings table, merge & deploy status back to the PR |
| **Live merge/deploy status** | Dashboard polls and shows `Merging…` → `Merged` → `Deploy triggered` in real time |
| **DB tracking** | `merge_status`, `deploy_status`, `deploy_url` stored per workflow |

---

## 🚀 Quick Start (5 minutes)

### Prerequisites

| Tool | Version | Install |
|------|---------|---------|
| Docker Desktop | ≥ 24.0 | https://docs.docker.com/get-docker/ |
| Docker Compose v2 | ≥ 2.20 | Included with Docker Desktop |
| Git | ≥ 2.40 | `brew install git` / `apt install git` |
| Ollama (optional) | ≥ 0.3 | https://ollama.ai |

Ports required: **3000, 5173, 5432, 8000, 8001, 8080, 8501**

### 1. Clone & Configure

```bash
git clone https://github.com/stonetusker/tuskersquad.git
cd tuskersquad

# Create your .env from the example
make env
# → Edit infra/.env with your values
```

### 2. (Optional) Pull LLM models

```bash
ollama pull qwen2.5:14b
ollama pull phi3:mini
ollama pull deepseek-coder:6.7b
```

### 3. Start all services

```bash
make fresh          # Clean build + start (recommended for first run)
# or
make up             # Build + start (keeps existing data)
```

Wait ~45 seconds. Then verify:

```bash
make health
```

### 4. Open the dashboard

```
http://localhost:5173
```

### 5. Trigger your first workflow

```bash
make simulate
# or directly:
curl -X POST http://localhost:8001/webhook/simulate \
     -H 'Content-Type: application/json' \
     -d '{"repo":"tuskeradmin/demo-store","pr_number":42}'
```

---

## 🔀 Enabling Auto-Merge

Edit `infra/.env`:

```env
# Merge the PR automatically when human clicks Approve
AUTO_MERGE_ON_APPROVE=true

# How to merge (merge | rebase | squash)
MERGE_STYLE=merge
```

A valid `GITEA_TOKEN` with write access to the repo is required.

---

## 🚀 Enabling Deploy on Merge

1. Add a Gitea Actions workflow to your repository:

   ```
   your-repo/.gitea/workflows/deploy.yml
   ```

   Use the template at `.gitea/workflows/deploy.yml` in this repo as a starting point.
   The workflow must have `on: workflow_dispatch`.

2. Edit `infra/.env`:

   ```env
   DEPLOY_ON_MERGE=true
   DEPLOY_BRANCH=main          # Branch to dispatch on
   DEPLOY_PIPELINE=deploy      # Workflow filename without .yml
   ```

3. Restart the stack:

   ```bash
   make stop && make up
   ```

After the next human **Approve**, TuskerSquad will:
1. Merge the PR
2. Dispatch the `deploy.yml` workflow
3. Post a `🚀 Deployment triggered` comment to the PR
4. Label the PR `tuskersquad:deployed`
5. Show live status in the dashboard

---

## 🎬 Live Demo Scenarios

```bash
# Scenario 1 — Security bug detected (EP01 video)
make demo-security

# Scenario 2 — Latency regression
make demo-latency

# Scenario 3 — Pricing bug
make demo-pricing

# Scenario 4 — All three bugs at once
make demo-all

# Reset to clean state
make demo-clean && make fresh
```

---

## 🏗 Architecture

```
┌──────────────┐   webhook   ┌────────────────────┐
│    Gitea     │ ──────────▶ │ Integration Service │ :8001
│  (Git + CI)  │             └────────┬───────────┘
└──────────────┘                      │ POST /api/workflow/start
       ▲ PR comment                   ▼
       │ + merge via API   ┌────────────────────┐
       └───────────────────│   LangGraph API    │ :8000
                           │                    │
                           │  Planner           │
                           │  ├─ Backend        │◀── Ollama LLMs
                           │  ├─ Frontend       │    (host:11434)
                           │  ├─ Security       │
                           │  └─ SRE            │
                           │  Challenger        │
                           │  QA Lead           │
                           │  Judge             │
                           │  ↓                 │
                           │  REVIEW_REQUIRED   │──▶ Human gate
                           │  APPROVE ──────────│──▶ Auto-merge
                           │                    │──▶ Auto-deploy
                           └────────┬───────────┘
                                    │ persist
                                    ▼
                           ┌────────────────────┐
                           │    PostgreSQL 15    │ :5432
                           └────────────────────┘
                                    ▲
                           ┌────────┴───────────┐
                           │  Dashboard (BFF)    │ :8501
                           └────────┬───────────┘
                                    │
                           ┌────────▼───────────┐
                           │  React Frontend     │ :5173
                           └────────────────────┘
```

### Service URLs

| Service | URL | Purpose |
|---------|-----|---------|
| **Frontend Dashboard** | http://localhost:5173 | Main UI — show this in demos |
| **LangGraph API docs** | http://localhost:8000/docs | REST API explorer |
| **Demo App** | http://localhost:8080/docs | E-commerce test target |
| **Gitea** | http://localhost:3000 | Git + PR + Actions |
| **Integration Service** | http://localhost:8001/docs | Webhook receiver |
| **Dashboard API** | http://localhost:8501/docs | BFF proxy |

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `GITEA_TOKEN` | — | Gitea personal access token (required for merge/deploy/comments) |
| `OLLAMA_URL` | `http://host.docker.internal:11434` | Ollama LLM endpoint |
| `AUTO_MERGE_ON_APPROVE` | `false` | Merge PR automatically on human APPROVE |
| `MERGE_STYLE` | `merge` | `merge` / `rebase` / `squash` |
| `DEPLOY_ON_MERGE` | `false` | Trigger Gitea Actions after merge |
| `DEPLOY_BRANCH` | `main` | Branch to run deploy on |
| `DEPLOY_PIPELINE` | `deploy` | Workflow filename (without `.yml`) |
| `BUG_PRICE` | `false` | Inject pricing bug into demo app |
| `BUG_SECURITY` | `false` | Inject auth bypass into demo app |
| `BUG_SLOW` | `false` | Inject latency into demo app |
| `JIRA_URL` | — | Jira instance URL |
| `JIRA_TOKEN` | — | Jira API token |
| `SLACK_WEBHOOK_URL` | — | Slack incoming webhook URL |
| `LATENCY_THRESHOLD_MS` | `500` | SRE p95 threshold in ms |

---

## 🔧 Makefile Commands

```bash
make fresh          # Clean slate build (use before demos)
make up             # Start services (preserves data)
make stop           # Stop services
make clean          # Stop + delete all volumes
make health         # Check all service health
make logs           # Tail langgraph-api logs
make logs-all       # Tail all logs
make simulate       # Fire a test workflow
make demo-security  # Enable security bug + fire workflow
make demo-latency   # Enable latency bug + fire workflow
make demo-pricing   # Enable pricing bug + fire workflow
make demo-all       # All bugs + workflow
make demo-clean     # Reset demo app to clean
```

---

## 🤖 Agent Model Assignments

| Agent | Model | Role |
|-------|-------|------|
| Planner | qwen2.5:14b | Selects which agents run |
| Backend | deepseek-coder:6.7b | pytest execution |
| Frontend | deepseek-coder:6.7b | Playwright E2E |
| Security | qwen2.5:14b | OWASP HTTP probes |
| SRE | qwen2.5:14b | p50/p95/p99 latency |
| Challenger | qwen2.5:14b | Finding disputes |
| QA Lead | phi3:mini | Summary + risk rating |
| Judge | qwen2.5:14b | APPROVE / REJECT / REVIEW_REQUIRED |

Configure in `config/models.yaml`. All agents have deterministic fallbacks when Ollama is not running.

---

## 🏢 Stonetusker Systems

**TuskerSquad** is the flagship product of [Stonetusker Systems](https://stonetusker.com), positioning us as the leading **Agentic AI as a Service** provider for engineering governance.

> *"We build the AI layer between your developers and production."*
