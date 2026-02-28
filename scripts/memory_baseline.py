import asyncio
from core.llm_client import LLMClient


async def run():

    client = LLMClient()

    print("Running Qwen Planner")

    r1 = await client.generate(

        "planner",

        "Say hello briefly."

    )

    print("Planner Response:", r1[:80])

    print("Running Backend Engineer")

    r2 = await client.generate(

        "backend_engineer",

        "Write python add function"

    )

    print("Backend Response:", r2[:80])


if __name__ == "__main__":

    asyncio.run(run())