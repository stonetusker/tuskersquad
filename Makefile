build:
	docker compose -f infra/docker-compose.yml up --build -d

down:
	docker compose -f infra/docker-compose.yml down

shell:
	docker exec -it tuskersquad-langgraph bash

ollama-test:
	docker exec -it tuskersquad-langgraph python scripts/check_ollama.py

logs:
	docker logs -f tuskersquad-langgraph
