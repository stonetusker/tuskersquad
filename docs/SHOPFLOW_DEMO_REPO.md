# ShopFlow Demo Repository

This document describes the contents and setup of the `tusker/shopflow` Gitea repository
that TuskerSquad uses as its target application for PR review demonstrations.

---

## What is ShopFlow?

ShopFlow is a simple e-commerce application included with TuskerSquad. It exists for one
purpose: to give TuskerSquad agents something real to test when a PR is submitted.

The agents run tests against it (backend API tests, frontend UI tests, security probes,
load tests) and report findings on the PR. Bug flags can be toggled in `infra/.env` to
inject known issues, which lets you verify that each agent correctly detects them.

---

## Repository contents

The shopflow repository should contain the following files (copied from `apps/backend/`
in the TuskerSquad project):

```
shopflow/
├── Dockerfile              ← Required for builder/deployer agents (copy from infra/Dockerfile.demo)
├── requirements.txt        ← Python dependencies
├── main.py                 ← FastAPI app entry point (exposes /health, /products, /login, /checkout, /orders)
├── models.py               ← SQLAlchemy models (Product, Order, User)
├── schemas.py              ← Pydantic schemas
├── auth.py                 ← JWT helpers
├── database.py             ← SQLAlchemy session
├── seed_data.py            ← Demo products and test user
├── bug_flags.py            ← Reads BUG_* env vars to inject controllable defects
├── routes/
│   ├── products.py         ← GET /products, GET /products/{id}, GET /categories
│   ├── auth.py             ← POST /login, POST /register
│   ├── checkout.py         ← POST /checkout
│   ├── orders.py           ← GET /orders  (auth-required)
│   └── user.py             ← GET /user/profile  (auth-required)
├── static/
│   └── index.html          ← Simple browser demo UI
└── tests/
    ├── api/
    │   ├── test_health.py          ← Tests /health endpoint
    │   ├── test_products.py        ← Tests GET /products and /categories
    │   └── test_checkout.py        ← Tests POST /checkout totals and edge cases
    └── ui/
        └── test_flows.py           ← Playwright tests for login → cart → checkout flow
```

---

## Initial setup (first time)

The `gitea-setup` container creates an **empty** `tusker/shopflow` repository in Gitea on
first boot. You must push the ShopFlow source into it:

```bash
# 1. Clone the auto-created empty repo
git clone http://tusker:tusker1234@localhost:3000/tusker/shopflow.git
cd shopflow

# 2. Copy ShopFlow source from TuskerSquad
cp -r /path/to/tuskersquad/apps/backend/* .
cp /path/to/tuskersquad/infra/Dockerfile.demo ./Dockerfile

# 3. Add .gitignore
cat > .gitignore << 'IGNORE'
__pycache__/
*.pyc
.env
shopflow.db
*.egg-info/
dist/
.pytest_cache/
IGNORE

# 4. Commit and push main branch
git add .
git commit -m "Initial ShopFlow application"
git push origin main
```

---

## How to create a test PR

```bash
# Inside the shopflow clone:

# 1. Create a feature branch
git checkout -b feature/test-change

# 2. Make any small change (e.g. a comment, a variable name, or a bug injection)
echo "# reviewed" >> main.py

# 3. Commit and push
git add main.py
git commit -m "Test: trigger TuskerSquad review"
git push origin feature/test-change

# 4. Open a PR in Gitea
# Visit http://localhost:3000/tusker/shopflow
# Click "New Pull Request"
# Set base: main, compare: feature/test-change
# Click "Create Pull Request"
```

TuskerSquad receives the webhook and begins the review pipeline within seconds.

---

## API routes (no /api prefix)

ShopFlow routes have **no** `/api` prefix. This is important for agent configuration:

| Method | Route              | Auth required | Notes                          |
|--------|--------------------|---------------|--------------------------------|
| GET    | /health            | No            | Returns `{"status": "ok"}`     |
| GET    | /products          | No            | Lists all products             |
| GET    | /products/{id}     | No            | Single product                 |
| GET    | /categories        | No            | Product categories             |
| POST   | /login             | No            | Returns JWT access_token       |
| POST   | /register          | No            | Creates user account           |
| POST   | /checkout          | Yes (Bearer)  | Processes order                |
| GET    | /orders            | Yes (Bearer)  | Lists user orders              |
| GET    | /user/profile      | Yes (Bearer)  | Returns user profile           |

**Test user credentials** (created by `seed_data.py`):
- Email: `test@example.com`
- Password: `password`

---

## Dockerfile requirements

For the `builder` and `deployer` agents to work, the Dockerfile must:

1. **Expose port 8080** — `EXPOSE 8080`
2. **Have a `/health` endpoint** returning HTTP 200 — the deployer health-checks this
3. **Accept `API_PREFIX` env var** — set to `""` by default (no prefix)

The included `Dockerfile.demo` satisfies all three requirements. Do not change the
exposed port without also updating `HEALTH_ENDPOINT` in `infra/.env`.

---

## Bug flags

Toggle these in `infra/.env` to inject bugs and test agent detection:

| Flag                  | Effect                                                         | Detected by     |
|-----------------------|----------------------------------------------------------------|-----------------|
| `BUG_PRICE=true`      | Checkout total uses float instead of Decimal (rounding errors) | backend agent   |
| `BUG_SECURITY=true`   | `/orders` returns 200 without auth (auth bypass)               | security agent  |
| `BUG_SLOW=true`       | `/checkout` sleeps 3s (p95 latency regression)                 | sre agent       |
| `BUG_JWT_NO_EXPIRY=true` | JWTs have no `exp` claim (tokens never expire)             | security agent  |
| `BUG_WEAK_PASSWORD=true` | Accepts 1-character passwords                              | security agent  |
| `BUG_INVENTORY=true`  | Catalog reports inflated stock counts                          | correlator      |
| `BUG_NO_ROLLBACK=true`| Order service doesn't roll back stock on payment failure       | correlator      |

After changing a flag, restart the relevant service:

```bash
docker compose -f infra/docker-compose.yml restart demo-backend
```

---

## Important: repo_validator abort behaviour

If TuskerSquad cannot access the shopflow repository, `repo_validator` will:

1. Post a **❌ Workflow Aborted: Validation Failed** comment on the PR with the exact error
2. Mark the workflow as `FAILED` in the database
3. **Skip all subsequent agents** — no backend/frontend/security/sre results will appear

This is intentional. Running agents when the source is unavailable produces misleading
green results (agents fall back to testing the permanent demo-backend, not the PR code).

If you see this error, the most common cause is a missing or incorrectly-scoped
`GITEA_TOKEN`. The token needs **repository** and **issue** read+write scopes.
