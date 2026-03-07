import os
import sys
import asyncio
from pathlib import Path

# Ensure repo root is on sys.path so `services` and `core` packages import correctly
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from services.langgraph_api.workflows.graph_builder import build_graph
import core.llm_client as llm_module


def test_graph_builder_uses_llm(monkeypatch, tmp_path):
    # Ensure the LLM path is enabled so the graph_builder attempts LLM calls
    monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")

    # Async fake generate that returns an APPROVE decision
    async def fake_generate(self, agent_name: str, prompt: str, temperature: float = 0):
        # Return a response that includes APPROVE so parsing logic picks it up
        return "APPROVE - test mock reason: safe to merge"

    # Patch the LLMClient.generate method
    monkeypatch.setattr(llm_module.LLMClient, "generate", fake_generate)

    # Invoke the graph and assert the decision uses the mocked LLM
    g = build_graph()
    res = g.invoke({"workflow_id": "test-1", "repository": "owner/repo", "pr_number": 1})

    assert res is not None
    assert "decision" in res
    assert res["decision"] == "APPROVE"
