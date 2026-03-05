import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

import asyncio
from core.llm_client import LLMClient

async def main():
    llm = LLMClient()

    response = await llm.generate(
        "planner",
        "Explain what a pull request is in one sentence.",
        temperature=0
    )

    print("\nLLM Response:\n")
    print(response)

asyncio.run(main())
