"""
LLM Client
==========
Wraps Ollama HTTP API with:
  - Per-call structured logging to DB (via callback)
  - File-based conversation log: /app/logs/llm_conversations.log
  - Retry + timeout
  - Model switching with warmup
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Callable

import httpx
import yaml

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

# ── File logger setup ─────────────────────────────────────────────────────────
LOG_DIR = Path(os.getenv("LOG_DIR", "/app/logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

_file_handler = logging.FileHandler(LOG_DIR / "llm_conversations.log")
_file_handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))

llm_file_logger = logging.getLogger("llm.conversations")
llm_file_logger.setLevel(logging.DEBUG)
llm_file_logger.addHandler(_file_handler)
llm_file_logger.propagate = False

logger = logging.getLogger("llm")


def _log_conversation(
    workflow_id: Optional[str],
    agent: str,
    model: str,
    prompt: str,
    response: Optional[str],
    duration_ms: int,
    success: bool,
    error: Optional[str] = None,
):
    """Write a structured record to the LLM conversation log file."""
    record = {
        "ts":          datetime.utcnow().isoformat(),
        "workflow_id": workflow_id,
        "agent":       agent,
        "model":       model,
        "duration_ms": duration_ms,
        "success":     success,
        "prompt":      prompt,
        "response":    response,
        "error":       error,
    }
    llm_file_logger.info(json.dumps(record, ensure_ascii=False))


class LLMClient:

    def __init__(self, config_path: str = "config/models.yaml"):
        config_path = os.path.join(os.path.dirname(__file__), "..", config_path)
        config_path = os.path.normpath(config_path)
        if not os.path.exists(config_path):
            # fallback relative to cwd
            config_path = "config/models.yaml"
        try:
            with open(config_path) as f:
                self.models = yaml.safe_load(f)
        except FileNotFoundError:
            # Minimal fallback config
            self.models = {
                k: {"model": "llama3.2:3b"} for k in
                ["backend_engineer", "frontend_engineer", "security_engineer",
                 "sre_engineer", "planner", "challenger", "qa_lead", "judge"]
            }

        self.active_model: Optional[str] = None
        self.model_lock   = asyncio.Lock()
        self.semaphore    = asyncio.Semaphore(1)
        # Optional DB persist callback: fn(workflow_id, agent, model, prompt, response, duration_ms, success, error)
        self._db_log_callback: Optional[Callable] = None

    def set_db_log_callback(self, callback: Callable):
        """Register a callback that persists conversations to the database."""
        self._db_log_callback = callback

    async def ensure_model_loaded(self, model_name: str):
        async with self.model_lock:
            if self.active_model == model_name:
                return
            logger.info("llm_model_switch → %s", model_name)
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    await client.post(
                        f"{OLLAMA_URL}/api/generate",
                        json={"model": model_name, "prompt": "hi", "stream": False},
                    )
                self.active_model = model_name
                logger.info("llm_model_ready model=%s", model_name)
            except Exception as e:
                logger.warning("llm_warmup_failed model=%s error=%s", model_name, e)

    async def generate(
        self,
        agent_name: str,
        prompt: str,
        temperature: float = 0.1,
        workflow_id: Optional[str] = None,
    ) -> str:
        model_name = self.models.get(agent_name, {}).get("model", "llama3.2:3b")
        await self.ensure_model_loaded(model_name)

        t0 = time.monotonic()
        response_text: Optional[str] = None
        error_text:    Optional[str] = None
        success = False

        async with self.semaphore:
            logger.info("llm_request agent=%s model=%s wf=%s", agent_name, model_name, workflow_id)
            try:
                async with httpx.AsyncClient(timeout=60) as client:
                    r = await client.post(
                        f"{OLLAMA_URL}/api/generate",
                        json={
                            "model":       model_name,
                            "prompt":      prompt,
                            "temperature": temperature,
                            "stream":      False,
                        },
                    )
                    r.raise_for_status()
                    response_text = r.json().get("response", "")
                    success = True
                    logger.info("llm_response agent=%s len=%d", agent_name, len(response_text))
            except Exception as exc:
                error_text = str(exc)
                logger.warning("llm_failed agent=%s error=%s", agent_name, exc)
                raise

        duration_ms = int((time.monotonic() - t0) * 1000)

        # File log
        _log_conversation(
            workflow_id=workflow_id,
            agent=agent_name,
            model=model_name,
            prompt=prompt,
            response=response_text,
            duration_ms=duration_ms,
            success=success,
            error=error_text,
        )

        # DB log (if callback registered)
        if self._db_log_callback:
            try:
                self._db_log_callback(
                    workflow_id=workflow_id,
                    agent=agent_name,
                    model=model_name,
                    prompt=prompt,
                    response=response_text,
                    duration_ms=duration_ms,
                    success=success,
                    error=error_text,
                )
            except Exception:
                logger.warning("llm_db_log_callback_failed")

        return response_text or ""
