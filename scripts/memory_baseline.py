import asyncio
import psutil
from core.llm_client import LLMClient


def get_memory_usage():
    mem = psutil.virtual_memory()
    return mem.used / (1024 ** 3)


async def run_test():
    client = LLMClient()

    print("Initial RAM (GB):", round(get_memory_usage(), 2))

    print("Running Qwen...")
    await client.generate("planner", "Say hello in one sentence.")
    print("After Qwen RAM (GB):", round(get_memory_usage(), 2))

    print("Running DeepSeek...")
    await client.generate("backend_engineer", "Write a simple Python function.")
    print("After DeepSeek RAM (GB):", round(get_memory_usage(), 2))


if __name__ == "__main__":
    asyncio.run(run_test())
