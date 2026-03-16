# TuskerSquad — Installation Guide

## Prerequisites

| Requirement | Minimum | Notes |
|-------------|---------|-------|
| Docker Desktop | 24.0 | https://docs.docker.com/get-docker/ |
| Docker Compose v2 | 2.20 | Included with Docker Desktop |
| Git | 2.40 | `brew install git` / `apt install git` |
| Ollama | 0.3 (optional) | https://ollama.ai — required for full AI features |

Ports required (must be free):

```
3000   Gitea
5173   React UI
5432   PostgreSQL
8000   LangGraph API
8001   Integration Service
8080   ShopFlow demo backend
8081   Catalog microservice
8082   Order microservice
8083   User microservice
8501   Dashboard BFF
```

---

## Quick Start (5 minutes)

### Step 1 — Clone

```bash
git clone https://github.com/stonetusker/tuskersquad
cd tuskersquad
```

### Step 2 — Configure

```bash
cp infra/.env.example infra/.env
```

Set `DOCKER_HOST_IP` in `infra/.env` to your machine's LAN IP so the ephemeral
container preview URL is accessible from a browser:

```bash
DOCKER_HOST_IP=192.168.0.108   # your machine's LAN IP
# or leave as localhost if you will only access it from the same machine
```

On Linux you may also need to update `OLLAMA_URL`:

```bash
OLLAMA_URL=http://192.168.0.108:11434   # use LAN IP, not localhost
```

### Step 3 — Start all services

```bash
make up
```

First build takes 3–5 minutes. Subsequent starts are fast.

### Step 4 — Initialise Gitea (first time only)

```bash
make setup
```

Copy the printed `GITEA_TOKEN` into `infra/.env`:

```bash
GITEA_TOKEN=<paste token here>
```

### Step 5 — Apply token and restart

```bash
make restart
```

### Step 6 — Verify

```bash
make health
```

All services should report healthy. Open:

- Dashboard: http://localhost:5173
- Gitea: http://localhost:3000 (login: `tusker` / `tusker1234`)
- API docs: http://localhost:8000/docs
- ShopFlow: http://localhost:8080

---

## Enable Full AI Features (Ollama)

Without Ollama, all agents work in deterministic mode (real HTTP probes, pytest,
static analysis). Pull these models for LLM-powered reasoning:

```bash
ollama pull qwen2.5:14b           # 9 GB — judge, correlator, security, SRE
ollama pull deepseek-coder:6.7b   # 4 GB — backend and frontend engineers
ollama pull phi3:mini             # 2 GB — QA lead summaries
```

The dashboard shows a status banner at the top of the left panel if Ollama is
unreachable or models are not pulled. The banner lists exactly which agents are
affected and the commands to fix it. It auto-dismisses when Ollama is available.

---

## Platform-Specific Notes

### macOS (Apple Silicon M1/M2/M3)

Docker Desktop runs natively. Ollama has native Apple Silicon support. Use
`DOCKER_HOST_IP=localhost` and `OLLAMA_URL=http://host.docker.internal:11434`.

### Linux

```bash
sudo usermod -aG docker $USER && newgrp docker
# Use your LAN IP for both DOCKER_HOST_IP and OLLAMA_URL
DOCKER_HOST_IP=$(hostname -I | awk '{print $1}')
OLLAMA_URL=http://$(hostname -I | awk '{print $1}'):11434
```

### Windows (WSL2)

Run all commands from inside WSL2. Docker Desktop must have WSL2 integration enabled.
Use `DOCKER_HOST_IP=host.docker.internal` and `OLLAMA_URL=http://host.docker.internal:11434`.

---

## Ephemeral Container Access

When a PR is deployed, TuskerSquad builds a Docker image from the PR code and runs an
isolated container. The container is accessible at a public URL before human approval:

```
http://{DOCKER_HOST_IP}:{auto-assigned-port}
```

Example PR comment:

```
Ephemeral deployment successful — Preview: http://192.168.0.108:54321
Container: pr-3-ephemeral-a1b2c3d4-...  port: 54321
```

**The container stays running until the human reviewer clicks Approve or Reject.**
It is only torn down by the Cleanup agent after the human decision.

The port is assigned automatically by the host OS — no port collisions when
multiple PRs are reviewed concurrently.

Container name format:

```
pr-{pr_number}-ephemeral-{workflow_uuid}

Example: pr-3-ephemeral-a1b2c3d4-e5f6-7890-abcd-ef1234567890
```

To inspect it manually while it is running:

```bash
docker ps --filter name=pr-
docker port pr-3-ephemeral-a1b2c3d4-... 8080   # shows assigned host port
```

---

## Configuration Reference

All configuration lives in `infra/.env`.

### Git Provider

```bash
GIT_PROVIDER=gitea          # gitea | github | gitlab

# Gitea (auto-configured by make setup)
GITEA_URL=http://tuskersquad-gitea:3000
GITEA_TOKEN=                # filled by make setup
GITEA_ADMIN_USER=tusker
GITEA_ADMIN_PASS=tusker1234

# GitHub
GITHUB_TOKEN=               # fine-grained PAT
GITHUB_WEBHOOK_SECRET=      # matches GitHub repo webhook secret

# GitLab
GITLAB_TOKEN=               # project or personal access token
GITLAB_WEBHOOK_SECRET=      # matches GitLab webhook token
```

### LLM Backend

```bash
OLLAMA_URL=http://host.docker.internal:11434
# Linux: use your LAN IP instead of host.docker.internal
```

### Ephemeral Container Access

```bash
# IP or hostname of the Docker host — used to build the preview URL
# shown to human reviewers in the PR comment and dashboard
DOCKER_HOST_IP=localhost          # local dev
DOCKER_HOST_IP=192.168.0.108      # LAN server
DOCKER_HOST_IP=my-server.example.com  # hostname
```

### Auto-Merge and Deploy

```bash
AUTO_MERGE_ON_APPROVE=false    # set true to merge automatically on Approve
MERGE_STYLE=merge              # merge | rebase | squash
DEPLOY_ON_MERGE=false          # dispatch a Gitea Actions workflow after merge
```

### Demo Bug Flags (ShopFlow)

```bash
BUG_PRICE=false            # checkout total inflated 35%
BUG_SECURITY=false         # auth bypass — invalid tokens accepted
BUG_SLOW=false             # artificial 3s delay on checkout
BUG_INVENTORY=false        # stock count reported as inflated
BUG_JWT_NO_EXPIRY=false    # JWTs issued with no expiry claim
BUG_WEAK_PASSWORD=false    # short passwords accepted
```

Toggle without restarting Postgres or Gitea:

```bash
make demo-security    # BUG_SECURITY=true
make demo-pricing     # BUG_PRICE=true
make demo-latency     # BUG_SLOW=true
make demo-all         # all bugs on
make demo-clean       # all bugs off
```

---

## Running a Test Workflow

1. Open Gitea at http://localhost:3000 — login `tusker` / `tusker1234`
2. Navigate to `tusker/shopflow`
3. Create a branch, make any change, push
4. Open a Pull Request against `main`
5. Watch the TuskerSquad dashboard at http://localhost:5173 — the pipeline starts within seconds

For a demo with visible bugs:

```bash
make demo-security     # enable auth bypass
# Open a PR — Security Engineer will flag it
# Judge will return REVIEW_REQUIRED
# Open the preview URL from the PR comment to inspect the live app
# Click Reject in the dashboard — Cleanup runs and container is removed
```

---

## Makefile Reference

| Command | Description |
|---------|-------------|
| `make up` | Build images and start all services |
| `make down` | Stop and remove containers (volumes preserved) |
| `make restart` | Recreate app services with fresh env (Gitea untouched) |
| `make setup` | First-time Gitea init: repo + webhook + source + token |
| `make health` | Check all service health endpoints |
| `make logs` | Follow all service logs |
| `make logs-api` | Follow langgraph-api logs only |
| `make build` | Force rebuild all images without cache |
| `make demo-security` | Enable security bug |
| `make demo-pricing` | Enable pricing bug |
| `make demo-latency` | Enable latency bug |
| `make demo-all` | Enable all bugs |
| `make demo-clean` | Disable all bugs |

---

## Full Teardown

```bash
# Stop containers, keep Gitea and Postgres data
make down

# Full wipe — remove all volumes (clean slate)
docker compose -f infra/docker-compose.yml down -v

# After full wipe, start fresh
make up && make setup
# copy GITEA_TOKEN to infra/.env
make restart
```

---

## Troubleshooting

**Gitea not connected in UI**
Run `make setup`, copy the `GITEA_TOKEN` into `infra/.env`, then `make restart`.

**Ephemeral container not visible in docker ps after deployment**
Check the pipeline order is v23+. In older versions cleanup ran before human_approval.
Upgrade to v23 or later.

**Preview URL not accessible from browser**
Set `DOCKER_HOST_IP` to your machine's actual LAN IP in `infra/.env`, then `make restart`.
Do not use `localhost` if you are accessing from another machine or mobile device.

**Builder: docker command not found**
Run `make down && make up` to rebuild the langgraph image which installs docker-ce-cli.

**Deployer: network tuskersquad-net not found**
Run `make down && make up` so Compose recreates the network with the pinned name.

**Agents returning [FLAG] with demo app warning**
This is expected when no ephemeral deployment is available. Create a real PR to
trigger the full build/deploy/test pipeline.

**LLM calls timing out or Ollama banner visible**
Check Ollama is running: `ollama list`. On Linux, verify `OLLAMA_URL` uses your
LAN IP. The dashboard banner shows the current status and what to fix.

**pytest errors: ERROR collecting tests/api/test_health.py**
Ensure you are running from the project root: `cd tuskersquad && pytest tests/api/ -v`.

---

## Directory Structure

```
tuskersquad/
├── agents/              18 AI agent modules (one directory per agent)
├── apps/
│   ├── backend/         ShopFlow demo app (FastAPI + SQLite)
│   ├── catalog_service/ ShopFlow catalog microservice
│   ├── order_service/   ShopFlow order microservice
│   ├── user_service/    ShopFlow user microservice
│   └── frontend/        React + Vite dashboard UI
├── config/
│   └── models.yaml      LLM model routing (edit to change any model)
├── core/
│   └── llm_client.py    Ollama wrapper + singleton
├── services/
│   ├── langgraph_api/   18-agent orchestrator (LangGraph + FastAPI)
│   ├── integration_service/  Webhook receiver (Gitea / GitHub / GitLab)
│   └── dashboard/       BFF proxy for the React UI + Ollama status endpoint
├── tests/
│   ├── api/             API tests for the ShopFlow demo app
│   ├── unit/            Unit tests for core components
│   └── integration/     End-to-end workflow tests
├── infra/
│   ├── docker-compose.yml
│   ├── .env.example
│   └── Dockerfile.*
└── Makefile
```
