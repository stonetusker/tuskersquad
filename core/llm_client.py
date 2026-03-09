"""
LLM Client
==========
Wraps Ollama HTTP API with structured logging and DB persistence.

SINGLETON: call get_llm_client() to get the shared instance.
All agents share the same instance so the DB log callback registered
in execute_workflow() is used by every LLM call in the pipeline.

Bug fixes vs previous version:
  - DB log and file log are written BEFORE re-raising exceptions,
    so failed calls are still recorded.
  - Module-level singleton ensures the DB callback set in
    pr_review_workflow is used by graph_builder and all agents.
"""

import asyncio
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import httpx
import yaml

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")

logger = logging.getLogger("llm")

# ── File logger — created lazily on first write ───────────────────────────────
_file_logger: Optional[logging.Logger] = None


def _get_file_logger() -> logging.Logger:
    global _file_logger
    if _file_logger is not None:
        return _file_logger
    log_dir = Path(os.getenv("LOG_DIR", "/app/logs"))
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / "llm_conversations.log")
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        fl = logging.getLogger("llm.conversations")
        fl.setLevel(logging.DEBUG)
        if not fl.handlers:
            fl.addHandler(handler)
        fl.propagate = False
        _file_logger = fl
    except Exception as exc:
        logger.warning("llm_file_log_init_failed: %s", exc)
        _file_logger = logger
    return _file_logger


def _log_to_file(record: dict) -> None:
    try:
        _get_file_logger().info(json.dumps(record, ensure_ascii=False))
    except Exception:
        pass


# ── Singleton ─────────────────────────────────────────────────────────────────
_instance: Optional["LLMClient"] = None


def get_llm_client() -> "LLMClient":
    """
    Return the module-level singleton LLMClient.
    All agents and graph nodes share this instance so that the DB log
    callback registered in execute_workflow() applies to every LLM call.
    """
    global _instance
    if _instance is None:
        _instance = LLMClient()
    return _instance


class LLMClient:

    def __init__(self, config_path: str = "config/models.yaml"):
        candidate = Path(__file__).parent.parent / config_path
        if not candidate.exists():
            candidate = Path(config_path)
        try:
            with open(candidate) as f:
                self.models: dict = yaml.safe_load(f) or {}
        except FileNotFoundError:
            logger.warning("models.yaml not found at %s — using llama3.2:3b for all agents", candidate)
            self.models = {}

        self.active_model: Optional[str] = None
        self.model_lock = asyncio.Lock()
        self.semaphore = asyncio.Semaphore(1)
        self._db_log_callback: Optional[Callable] = None

    def set_db_log_callback(self, callback: Callable) -> None:
        """Register a function that persists LLM call records to the database."""
        self._db_log_callback = callback

    async def ensure_model_loaded(self, model_name: str) -> None:
        async with self.model_lock:
            if self.active_model == model_name:
                return
            logger.info("llm_model_switch model=%s", model_name)
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    await client.post(
                        f"{OLLAMA_URL}/api/generate",
                        json={"model": model_name, "prompt": "hi", "stream": False},
                    )
                self.active_model = model_name
                logger.info("llm_model_ready model=%s", model_name)
            except Exception as exc:
                logger.warning("llm_warmup_failed model=%s err=%s", model_name, exc)

    async def generate(
        self,
        agent_name: str,
        prompt: str,
        temperature: float = 0.1,
        workflow_id: Optional[str] = None,
    ) -> str:
        model_cfg  = self.models.get(agent_name) or {}
        model_name = model_cfg.get("model", "llama3.2:3b")

        await self.ensure_model_loaded(model_name)

        t0             = time.monotonic()
        response_text: Optional[str] = None
        error_text:    Optional[str] = None
        success        = False
        exc_to_raise   = None

        try:
            async with self.semaphore:
                logger.info("llm_request agent=%s model=%s wf=%s", agent_name, model_name, workflow_id)
                try:
                    async with httpx.AsyncClient(timeout=120) as client:
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
                        logger.info("llm_response agent=%s chars=%d", agent_name, len(response_text))
                except BaseException as exc:
                    # Catch BaseException (includes CancelledError from asyncio.wait_for timeout)
                    error_text   = str(exc)
                    exc_to_raise = exc
                    logger.warning("llm_failed agent=%s model=%s err=%s", agent_name, model_name, exc)
        finally:
            # Always write logs — even if cancelled by asyncio.wait_for timeout
            duration_ms = int((time.monotonic() - t0) * 1000)
            record = {
                "ts":          datetime.utcnow().isoformat(),
                "workflow_id": workflow_id,
                "agent":       agent_name,
                "model":       model_name,
                "duration_ms": duration_ms,
                "success":     success,
                "prompt":      prompt[:2000],
                "response":    response_text,
                "error":       error_text,
            }
            _log_to_file(record)
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
                    logger.debug("llm_db_log_callback_failed")

        if exc_to_raise is not None:
            raise exc_to_raise

        return response_text or ""
