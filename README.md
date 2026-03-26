# TuskerSquad

### Agentic AI PR Governance Platform

18 specialised AI agents. One human decision. Automatic build, deploy, test, and merge.

---

## Start Here

If you're new to TuskerSquad, these will give you a quick overview:

Introduction video  
https://www.youtube.com/watch?v=0HfhU-gw_KI

End-to-end demo  
https://www.youtube.com/watch?v=JFrBxMJt0ZI

Slide deck (architecture and deep dive)  
https://stonetusker.com/tools/tuskersquad/TuskerSquad-Demo-Deck.pdf

---

## What is TuskerSquad?

TuskerSquad watches every Pull Request and runs a complete automated review pipeline.

It does more than review code.  
It validates how your system behaves at runtime.

For every PR, it:

- Clones the code  
- Builds a Docker image  
- Deploys it into an isolated environment  
- Runs API tests  
- Executes security checks  
- Measures performance (p95 latency)  
- Analyses logs across services  
- Correlates findings into a root cause  

It then makes a decision:

Approve, Reject, or Review Required  
with a detailed explanation posted back to the PR.

---

## Why TuskerSquad Exists

We have automated how we build code.  
We have automated how we deploy code.

But the decision to ship is still manual.

TuskerSquad brings that decision layer into your pipeline.

---

## Key Differentiators

### Zero AI tooling cost

TuskerSquad runs fully locally using Ollama.

- No external API calls  
- No data leaves your infrastructure  
- No per-request cost  

All models run locally. No dependency on external services.

---

### Agents structured like a real engineering team

Each agent represents a real role:

- Tech Lead (Planner)  
- Backend Engineer  
- Security Engineer  
- SRE  
- QA Engineer  
- Architect  
- Engineering Manager (Judge)  

A process that usually takes 1 to 3 days  
runs automatically in under 5 minutes.

---

### Cross-service root cause analysis

TuskerSquad connects:

- API failures  
- Logs  
- Service interactions  

Using correlation IDs across microservices.

The output is clear and actionable:

- What failed  
- Where it failed  
- How to fix it  

---

## The 18-agent pipeline

Every PR triggers this pipeline:

```
Repo Validator → Planner → Backend → Frontend → Security → SRE
                               → Builder → Deployer → Tester → API Validator
                               → Security Runtime → Runtime Analyser → Log Inspector
                               → Correlator → Challenger → QA Lead → Judge
                                    ├── APPROVE / REJECT → Cleanup → END
                                    └── REVIEW_REQUIRED → Human Approval → Cleanup
```

---

## LLM usage

TuskerSquad uses local models through Ollama.

Only specific agents rely on LLM reasoning:

- qwen2.5:14b  
  Used by Judge and Correlator for decision-making and root cause reasoning  

- phi3:mini  
  Used by QA Lead for summarising findings and risk levels  

All other agents are deterministic and do not depend on LLMs.

---

## Quick Start

```bash
git clone https://github.com/stonetusker/tuskersquad
cd tuskersquad

cp infra/.env.example infra/.env

make up
docker logs tuskersquad-gitea-setup | grep GITEA_TOKEN
# copy token to infra/.env
make restart


open http://localhost:5173
```

---

## Enable AI models (one-time)

```bash
ollama pull qwen2.5:14b
ollama pull phi3:mini
```

---

## What happens during a PR

- PR is detected via webhook  
- Code is built and deployed in isolation  
- Tests, security checks, and performance validation run  
- Logs are analysed  
- Findings are correlated  
- A final decision is posted to the PR  

All of this completes in 2 to 4 minutes.

---

## Ephemeral environments

Each PR runs in its own isolated container.

- No shared state  
- No environment drift  
- Clean teardown after completion  

A preview URL is generated automatically.

---

## System architecture

- 18-agent orchestration using LangGraph  
- Local LLM execution using Ollama  
- Full audit trail stored in Postgres  
- React dashboard for visibility  

---

## Dashboard

- Live agent execution timeline  
- Full reasoning logs  
- PR diff with findings  
- Human approval interface  
- Merge and deployment tracking  

---

## Demo application (ShopFlow)

TuskerSquad includes a demo application with intentional bugs.

You can simulate:

- Security issues  
- Latency problems  
- Pricing bugs  
- JWT misconfigurations  

Example:

```bash
make demo-security
make demo-latency
make demo-all
```

---

## Git provider support

- Gitea (default)  
- GitHub  
- GitLab  

Integration is webhook-based.

---

## Contributing

Open an issue before submitting large changes.

This project is open to contributions from:

- Platform engineers  
- DevOps teams  
- Security engineers  
- AI and agent system builders  

---

## License

MIT License  
© Stonetusker Systems Private Limited
