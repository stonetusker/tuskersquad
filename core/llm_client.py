
import asyncio
import httpx
import yaml
import logging
import os

# Allow runtime override via environment (Docker compose or host)
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

logger = logging.getLogger("llm")

class LLMClient:

    def __init__(self, config_path="config/models.yaml"):
        with open(config_path) as f:
            self.models = yaml.safe_load(f)

        self.active_model = None
        self.model_lock = asyncio.Lock()
        self.semaphore = asyncio.Semaphore(1)

    async def ensure_model_loaded(self, model_name: str):

        async with self.model_lock:

            if self.active_model == model_name:
                return

            logger.info(f"Switching model → {model_name}")

            async with httpx.AsyncClient(timeout=120) as client:
                await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": model_name,
                        "prompt": "warmup",
                        "stream": False
                    }
                )

            self.active_model = model_name

    async def generate(self, agent_name: str, prompt: str, temperature: float = 0):

        model_name = self.models[agent_name]["model"]

        await self.ensure_model_loaded(model_name)

        async with self.semaphore:

            logger.info(f"Agent {agent_name} invoking model {model_name}")

            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    f"{OLLAMA_URL}/api/generate",
                    json={
                        "model": model_name,
                        "prompt": prompt,
                        "temperature": temperature,
                        "stream": False
                    }
                )

            result = response.json()["response"]

            logger.info("LLM response received")

            return result
