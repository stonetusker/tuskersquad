import os
import asyncio
import httpx
from typing import Dict

from core.model_router import ModelRouter
from core.logging import get_logger
import uuid


class LLMClient:
    """
    Enterprise Ollama client with:
    - Model routing
    - Concurrency control
    - Dynamic model switching
    - Timeout + retry
    """

    def __init__(self):
        self.ollama_host = os.getenv(
            "OLLAMA_HOST",
            "http://host.docker.internal:11434"
        )
        self.timeout_seconds = int(os.getenv("REQUEST_TIMEOUT_SECONDS", 120))
        self.max_concurrency = int(os.getenv("MAX_LLM_CONCURRENCY", 5))

        self.semaphore = asyncio.Semaphore(self.max_concurrency)
        self.router = ModelRouter()
        self.logger = get_logger("LLMClient")

        self.current_loaded_model = None

    async def _switch_model_if_needed(self, model_name: str):

        if self.current_loaded_model == model_name:
            return

        if self.current_loaded_model:

            await self._unload_model(
                self.current_loaded_model
            )

        self.logger.info(
            f"Switching model from {self.current_loaded_model} to {model_name}"
        )

        self.current_loaded_model = model_name

    async def generate(
        self,
        agent_name: str,
        prompt: str,
        max_tokens: int = 1024
    ) -> str:

        async with self.semaphore:

            # ⭐ Create Trace ID
            trace_id = str(uuid.uuid4())

            self.logger.info(
                f"TRACE={trace_id} agent={agent_name} starting inference"
            )

            config: Dict = self.router.get_model_config(agent_name)

            model_name = config["model"]
            temperature = config["temperature"]

            await self._switch_model_if_needed(model_name)

            payload = {
                "model": model_name,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens
                }
            }

            retries = 2

            for attempt in range(retries + 1):

                try:

                    async with httpx.AsyncClient(
                        timeout=self.timeout_seconds
                    ) as client:

                        response = await client.post(
                            f"{self.ollama_host}/api/generate",
                            json=payload
                        )

                        response.raise_for_status()

                        result = response.json()

                        self.logger.info(
                            f"TRACE={trace_id} completed successfully"
                        )

                        return result.get("response", "")

                except Exception as e:

                    self.logger.error(
                        f"TRACE={trace_id} failed attempt {attempt+1} error={str(e)}"
                    )

                    if attempt == retries:
                        raise e

                    await asyncio.sleep(2)
                
    async def _unload_model(self, model_name: str):
        """
        Explicitly request Ollama to unload a model.
        """
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                await client.post(
                    f"{self.ollama_host}/api/generate",
                    json={
                        "model": model_name,
                        "keep_alive": 0
                    }
                )

            self.logger.info(f"Requested unload of {model_name}")

        except Exception as e:
            self.logger.warning(f"Unload failed: {str(e)}")
