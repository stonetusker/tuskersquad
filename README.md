# TuskerSquad — AI Engineering Governance Platform

## Quick Start

### ⚠️ IMPORTANT: Clean Start (first time or after errors)

If you have run docker compose before, always do a clean start to avoid stale volumes:

```bash
cd infra
docker compose down -v   # removes old volumes including DB data
docker compose up --build
```

Or use the Makefile:
```bash
make fresh   # clean + build + start
```

### Normal Start (after initial setup)
```bash
docker compose -f infra/docker-compose.yml up --build
```

### Ports
| Service          | URL                      |
|-----------------|--------------------------|
| Frontend (UI)   | http://localhost:5173    |
| Dashboard API   | http://localhost:8501    |
| LangGraph API   | http://localhost:8000    |
| Integration Svc | http://localhost:8001    |
| Demo Backend    | http://localhost:8080    |
| Gitea           | http://localhost:3000    |

### Using the Demo
1. Open http://localhost:5173
2. Enter a repo name (e.g. `tusker/demo`) and PR number
3. Click **Start Workflow**
4. Watch agents run in the timeline
5. When status shows `WAITING_HUMAN_APPROVAL`, use Approve/Reject/Retest

### Demo Bug Flags
Toggle intentional bugs in the demo e-commerce app:
```bash
make demo-bugs-on    # enable pricing, latency and security bugs
make demo-bugs-off   # disable all bugs
```

### Troubleshooting

**`database "tusker" does not exist`**  
This means stale postgres data. Fix: `docker compose down -v && docker compose up --build`

**Services show WAITING status**  
Services have correct dependency ordering. Postgres must be healthy before langgraph starts.
Wait ~30 seconds after `up` for all services to initialise.

**LangGraph health check failing**  
The service waits for the database to be ready. Check with: `make logs-svc SVC=langgraph-api`
