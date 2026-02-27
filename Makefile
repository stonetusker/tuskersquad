build:
\tdocker compose -f infra/docker-compose.yml up --build -d

down:
\tdocker compose -f infra/docker-compose.yml down

shell:
\tdocker exec -it tuskersquad-langgraph bash

ollama-test:
\tdocker exec -it tuskersquad-langgraph python scripts/check_ollama.py

logs:
\tdocker logs -f tuskersquad-langgraph
