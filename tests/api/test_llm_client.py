import pytest
import asyncio

from core.llm_client import LLMClient


@pytest.mark.asyncio
async def test_planner_generation():

    client = LLMClient()

    result = await client.generate(

        "planner",

        "Say hello."

    )

    assert isinstance(result, str)

    assert len(result) > 0
