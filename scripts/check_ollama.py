import os
import httpx

host=os.getenv("OLLAMA_HOST","http://host.docker.internal:11434")

print("Checking Ollama:",host)

r=httpx.get(f"{host}/api/tags",timeout=30)

print(r.json())
