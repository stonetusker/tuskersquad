import os
import asyncio
import httpx
import uuid
import time
import psutil

from typing import Dict

from core.model_router import ModelRouter
from core.logging import get_logger


class LLMClient:

    """
    Enterprise Ollama Client

    - Model routing
    - Concurrency control
    - Explicit unload
    - Cold start detection
    - Memory guard
    - Latency tracking
    - Persistent HTTP client
    """

    def __init__(self):

        self.model_warm_state = {}

        self.memory_guard_threshold = int(
            os.getenv("MEMORY_GUARD_PERCENT", 85)
        )

        self.ollama_host = os.getenv(
            "OLLAMA_HOST",
            "http://host.docker.internal:11434"
        )

        self.timeout_seconds = int(
            os.getenv("REQUEST_TIMEOUT_SECONDS", 120)
        )

        self.max_concurrency = int(
            os.getenv("MAX_LLM_CONCURRENCY", 5)
        )

        self.semaphore = asyncio.Semaphore(
            self.max_concurrency
        )

        self.router = ModelRouter()

        self.logger = get_logger("LLMClient")

        self.current_loaded_model = None

        # Persistent HTTP client
        self.http = httpx.AsyncClient(
            timeout=self.timeout_seconds
        )

    # --------------------------------------------------

    def _check_memory_pressure(self):

        mem = psutil.virtual_memory()

        if mem.percent > self.memory_guard_threshold:

            self.logger.warning(
                f"Memory pressure high {mem.percent}%"
            )

            raise RuntimeError(
                "Memory pressure guard triggered."
            )

    # --------------------------------------------------

    async def _unload_model(self, model_name: str):

        try:

            await self.http.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": model_name,
                    "keep_alive": 0
                }
            )

            self.logger.info(
                f"Requested unload of {model_name}"
            )

        except Exception as e:

            self.logger.warning(
                f"Unload failed {model_name}: {str(e)}"
            )

    # --------------------------------------------------

    async def _switch_model_if_needed(self, model_name: str):

        if self.current_loaded_model == model_name:
            return

        if self.current_loaded_model:
            await self._unload_model(
                self.current_loaded_model
            )

        cold_start = model_name not in self.model_warm_state

        if cold_start:
            self.logger.info(
                f"Cold start loading {model_name}"
            )
            self.model_warm_state[model_name] = True

        self.logger.info(
            f"Switching model from "
            f"{self.current_loaded_model} "
            f"to {model_name}"
        )

        self.current_loaded_model = model_name

    # --------------------------------------------------

    async def generate(
        self,
        agent_name: str,
        prompt: str,
        max_tokens: int = 1024
    ) -> str:

        async with self.semaphore:

            self._check_memory_pressure()

            trace_id = str(uuid.uuid4())

            self.logger.info(
                f"TRACE={trace_id} "
                f"agent={agent_name} start"
            )

            config: Dict = self.router.get_model_config(
                agent_name
            )

            model_name = config["model"]
            temperature = config["temperature"]

            await self._switch_model_if_needed(
                model_name
            )

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

            start_time = time.time()

            for attempt in range(retries + 1):

                try:

                    response = await self.http.post(
                        f"{self.ollama_host}/api/generate",
                        json=payload
                    )

                    response.raise_for_status()

                    result = response.json()

                    latency = round(
                        time.time() - start_time,
                        2
                    )

                    self.logger.info(
                        f"TRACE={trace_id} "
                        f"success latency={latency}s"
                    )

                    return result.get("response", "")

                except Exception as e:

                    self.logger.error(
                        f"TRACE={trace_id} "
                        f"attempt={attempt+1} "
                        f"error={str(e)}"
                    )

                    if attempt == retries:
                        raise RuntimeError(
                            f"Inference failed "
                            f"TRACE={trace_id}"
                        ) from e

                    await asyncio.sleep(2)