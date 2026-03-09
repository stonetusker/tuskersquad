"""
LLM Client
==========
Wraps Ollama HTTP API.

Key design decisions:
  - Log directory creation is DEFERRED to first use (not module import),
    so this file is safe to import during Docker build / pip install.
  - Every generate() call writes a structured JSON record to the log file
    and optionally persists to the DB via a registered callback.
  - Model warmup is best-effort; failure does not crash the agent.
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
    """Return the file logger, creating it (and the log dir) on first call."""
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
        if not fl.handlers:          # avoid duplicate handlers on reload
            fl.addHandler(handler)
        fl.propagate = False
        _file_logger = fl
    except Exception as exc:
        logger.warning("llm_file_log_init_failed: %s — logging to stderr only", exc)
        _file_logger = logger          # fall back to normal logger

    return _file_logger


def _log_to_file(record: dict) -> None:
    try:
        _get_file_logger().info(json.dumps(record, ensure_ascii=False))
    except Exception:
        pass


class LLMClient:

    def __init__(self, config_path: str = "config/models.yaml"):
        # Resolve config relative to this file's location, then fall back to cwd
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
        model_cfg = self.models.get(agent_name) or {}
        model_name = model_cfg.get("model", "llama3.2:3b")

        await self.ensure_model_loaded(model_name)

        t0 = time.monotonic()
        response_text: Optional[str] = None
        error_text: Optional[str] = None
        success = False

        async with self.semaphore:
            logger.info("llm_request agent=%s model=%s wf=%s", agent_name, model_name, workflow_id)
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    r = await client.post(
                        f"{OLLAMA_URL}/api/generate",
                        json={
                            "model": model_name,
                            "prompt": prompt,
                            "temperature": temperature,
                            "stream": False,
                        },
                    )
                    r.raise_for_status()
                    response_text = r.json().get("response", "")
                    success = True
                    logger.info("llm_response agent=%s chars=%d", agent_name, len(response_text))
            except Exception as exc:
                error_text = str(exc)
                logger.warning("llm_failed agent=%s err=%s", agent_name, exc)
                raise

        duration_ms = int((time.monotonic() - t0) * 1000)

        # Write to log file (deferred creation — safe during Docker build)
        _log_to_file({
            "ts": datetime.utcnow().isoformat(),
            "workflow_id": workflow_id,
            "agent": agent_name,
            "model": model_name,
            "duration_ms": duration_ms,
            "success": success,
            "prompt": prompt,
            "response": response_text,
            "error": error_text,
        })

        # Persist to DB if callback is registered
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

        return response_text or ""
