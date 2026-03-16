# TuskerSquad

### Agentic AI PR Governance Platform — by Stonetusker Systems

> **18 specialised AI agents. One human decision. Automatic build, deploy, test, and merge.**

TuskerSquad watches every Pull Request on your Git repository and runs a complete
autonomous review: it clones the PR code, builds a Docker image, deploys an ephemeral
container, executes API tests, runs OWASP security probes, measures p95 latency, inspects
microservice logs, correlates findings across services, and delivers a final decision —
Approve, Reject, or Review Required — complete with a detailed comment posted back to the PR.

When the result is **Approve**, TuskerSquad can automatically merge the PR and trigger your
deploy pipeline. When it is **Review Required**, a human approves or rejects from the live
dashboard and can open the running ephemeral container in a browser to inspect it before
deciding. Nothing ships until both the AI squad and the human agree it is safe.

---

## Why TuskerSquad

| Capability | TuskerSquad | GitHub Copilot | SonarQube | Manual Review |
|------------|:-----------:|:--------------:|:---------:|:-------------:|
| Ephemeral build & deploy per PR | ✅ | ❌ | ❌ | ❌ |
| Live runtime security probes | ✅ | ❌ | ❌ | ❌ |
| p95 latency / SRE analysis | ✅ | ❌ | ❌ | ❌ |
| Cross-service log correlation | ✅ | ❌ | ❌ | ❌ |
| 18 specialised AI agents | ✅ | Partial | ❌ | ❌ |
| Customisable agents and models | ✅ | ❌ | Partial | ❌ |
| Zero LLM API cost (local Ollama) | ✅ | ❌ | ❌ | N/A |
| Open source — MIT licence | ✅ | ❌ | ❌ | N/A |
| 100% self-hosted, no vendor lock-in | ✅ | ❌ | Partial | ✅ |
| Air-gapped / offline operation | ✅ | ❌ | ❌ | N/A |
| Multi-provider (Gitea / GitHub / GitLab) | ✅ | ❌ | Partial | ✅ |
| Human-in-the-loop approval gate | ✅ | ❌ | ❌ | ✅ |
| Auto-merge + deploy on approve | ✅ | ❌ | ❌ | ❌ |
| Full LLM conversation audit trail | ✅ | ❌ | ❌ | N/A |

---

## Three Unique Differentiators

### 1 — Zero AI Tooling Cost

TuskerSquad runs on Ollama — a free, open-source local LLM runtime. The models
(qwen2.5:14b, deepseek-coder:6.7b, phi3:mini) are open-weight and downloaded once.
The marginal cost of your thousandth PR review is the same as the first: electricity.
Your source code never touches a cloud API. If Ollama is unreachable, a dashboard
warning banner lists exactly which agents are affected and the commands to resolve it.

### 2 — Agents Structured Like Your Agile Team

Each agent maps to a real engineering role: Tech Lead (Planner), Backend Dev, AppSec,
Site Reliability, CI/CD Pipeline (Builder+Deployer), QA Engineer, On-Call Engineer
(Log Inspector), Senior Architect (Correlator), and Engineering Manager (Judge). The
same review that takes 1-3 days in a sprint runs automatically in under 5 minutes.

### 3 — Cross-Layer Root Cause Analysis

The Correlator joins client-side HTTP probe findings with server-side structured log
events, linked by correlation_id across microservices. The developer receives a
three-sentence diagnosis: what the user sees, which service caused it, and how to fix it.

---

## The 18-Agent Pipeline

Every PR triggers this pipeline automatically via LangGraph state management:

```
Repo Validator → Planner → Backend → Frontend → Security → SRE
                               → Builder → Deployer → Tester → API Validator
                               → Security Runtime → Runtime Analyser → Log Inspector
                               → Correlator → Challenger → QA Lead → Judge
                                    ├── APPROVE / REJECT → Cleanup → END
                                    └── REVIEW_REQUIRED  → Human Approval
                                                               → Cleanup → END (or Retest)
```

The ephemeral container stays running while the human reviews it, and is only
torn down after the human clicks Approve or Reject.

| Agent | What it does |
|-------|-------------|
| Repo Validator | Confirms branch and PR exist and are accessible |
| Planner | Scopes the review, analyses PR diff |
| Backend Engineer | Runs pytest API tests against the deployed PR code |
| Frontend Engineer | UI behaviour, form validation, accessibility checks |
| Security Engineer | OWASP probes: auth bypass, SQLi, JWT manipulation, CORS |
| SRE Engineer | p95 latency measurement, SLA breach detection |
| Builder | Clones PR branch, builds Docker image in isolated workspace |
| Deployer | Launches ephemeral container, exposes public URL for human review |
| Tester | Executes automated test suite against the live PR container |
| API Validator | Schema and contract validation |
| Security Runtime | Live attack probes against the running container |
| Runtime Analyser | CPU/memory profiling, log analysis while app runs |
| Log Inspector | Reads structured /logs/events from every microservice |
| Correlator | Joins client findings + server logs into root cause chains |
| Challenger | Disputes findings affected by environment variance |
| QA Lead | Synthesises all findings into an overall risk level |
| Judge | Makes the final APPROVE / REJECT / REVIEW_REQUIRED decision |
| Cleanup | Stops container, removes image, wipes workspace |

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/stonetusker/tuskersquad
cd tuskersquad

# 2. Configure
cp infra/.env.example infra/.env
# Set DOCKER_HOST_IP to your machine IP so PR preview links work from a browser

# 3. Start all services
make up

# 4. First-time Gitea setup
make setup
# Copy the GITEA_TOKEN from the output into infra/.env

# 5. Apply token and restart
make restart

# 6. Open the dashboard
open http://localhost:5173
```

Pull Ollama models for full AI (one-time download):

```bash
ollama pull qwen2.5:14b
ollama pull deepseek-coder:6.7b
ollama pull phi3:mini
```

---

## LLM Model Routing

Only three agents call LLMs directly. All other agents are fully deterministic.

| Agent(s) | Model | Role |
|----------|-------|------|
| Judge · Correlator · Security · SRE · Planner | qwen2.5:14b | Complex reasoning and decisions |
| Backend Engineer · Frontend Engineer | deepseek-coder:6.7b | Code-native analysis |
| QA Lead | phi3:mini | Fast concise risk summaries |

Switch any model in `config/models.yaml` with no code changes needed.

---

## Ephemeral Container Access

When a PR is deployed, the preview URL appears in both the PR comment and dashboard:

```
Ephemeral deployment successful — Preview: http://192.168.0.108:54321
```

The port is assigned automatically by the host OS (no collisions for concurrent reviews).
The container stays running until the human reviewer decides.

Set your machine IP in `infra/.env`:

```bash
DOCKER_HOST_IP=192.168.0.108   # your LAN IP or hostname
```

---

## Services

| Service | Port | Description |
|---------|------|-------------|
| react-frontend | 5173 | Vite + React workflow dashboard |
| dashboard-bff | 8501 | FastAPI proxy for the React UI |
| langgraph-api | 8000 | 18-agent orchestrator + REST API |
| integration-service | 8001 | Webhook receiver (Gitea / GitHub / GitLab) |
| gitea | 3000 | Self-hosted Git server |
| postgres | 5432 | Workflow state, findings, LLM logs |
| demo-backend | 8080 | ShopFlow demo e-commerce app |
| catalog-service | 8081 | ShopFlow catalog microservice |
| order-service | 8082 | ShopFlow order microservice |
| user-service | 8083 | ShopFlow user microservice |

---

## Git Provider Setup

**Gitea (default):** fully automatic via `make setup`.

**GitHub:**
1. Create a fine-grained PAT with `repo` and `pull_requests` scopes
2. Set `GIT_PROVIDER=github`, `GITHUB_TOKEN`, `GITHUB_WEBHOOK_SECRET` in `infra/.env`
3. Add webhook to your repo: `http://<host>:8001/github/webhook`
4. Run `make restart`

**GitLab:**
1. Create a project access token with `api` scope
2. Set `GIT_PROVIDER=gitlab`, `GITLAB_TOKEN`, `GITLAB_WEBHOOK_SECRET` in `infra/.env`
3. Add webhook: `http://<host>:8001/gitlab/webhook`
4. Run `make restart`

---

## Demo App — ShopFlow

ShopFlow is the intentionally buggy e-commerce test target. Toggle bugs for demos:

| Flag | Effect | Agent that detects it |
|------|--------|----------------------|
| BUG_PRICE=true | Checkout total inflated 35% | SRE, Correlator |
| BUG_SECURITY=true | Auth bypass — invalid tokens accepted | Security Engineer |
| BUG_SLOW=true | 3s artificial delay on checkout | SRE |
| BUG_INVENTORY=true | Inflated stock count reported | Log Inspector |
| BUG_JWT_NO_EXPIRY=true | JWTs issued with no expiry | Security Engineer |
| BUG_WEAK_PASSWORD=true | Short passwords accepted | Security Engineer |

```bash
make demo-security    # enable auth bypass bug
make demo-pricing     # enable pricing bug
make demo-latency     # enable latency bug
make demo-all         # all bugs on
make demo-clean       # all bugs off
```

Demo login: `test@example.com` / `password`

Running the test suite:

```bash
pytest tests/api/ -v
# All 12 tests should pass with no bug flags active
```

---

## Dashboard Features

- **Ollama status banner** — visible when Ollama is unreachable or models are missing; auto-dismisses when fixed
- **Relative timestamps** — workflow list shows "5 minutes ago", "Today 14:32" instead of raw time values
- **Live workflow list** — all PR reviews with status and timing
- **Agent timeline** — real-time view of each agent running
- **Findings panel** — severity-sorted, with root cause chains from Correlator
- **LLM reasoning** — full prompt and response for every AI call
- **Diff viewer** — PR changes alongside agent comments
- **Human approval** — Approve / Reject / Retest with live link to the running container
- **Merge & deploy status** — polls in real time until merge and deploy complete

---

## Makefile Reference

```bash
make up            # Build and start all services
make down          # Stop containers (data preserved)
make restart       # Recreate app services with updated .env
make setup         # First-time Gitea initialisation
make health        # Check all service health endpoints
make logs          # Follow all service logs
make build         # Force rebuild without cache
make demo-security # Enable security bug
make demo-pricing  # Enable pricing bug
make demo-latency  # Enable latency bug
make demo-all      # Enable all bugs
make demo-clean    # Disable all bugs
```

---

## Contributing

Open an issue before submitting a large pull request. Python 3.11+, black formatter.

---

## License

MIT — see [COPYRIGHT.md](COPYRIGHT.md).

Copyright (c) 2025 Stonetusker Systems
