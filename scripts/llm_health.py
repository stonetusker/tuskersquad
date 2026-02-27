import httpx
import os

host=os.getenv(
    "OLLAMA_HOST",
    "http://host.docker.internal:11434"
)

r=httpx.get(f"{host}/api/tags")

print("LLM HEALTH OK")

print(r.json())
