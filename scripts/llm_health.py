import httpx
import os


OLLAMA = os.getenv(
    "OLLAMA_HOST",
    "http://host.docker.internal:11434"
)


def run():

    print("Checking Ollama connectivity...")

    r = httpx.get(
        f"{OLLAMA}/api/tags",
        timeout=30
    )

    r.raise_for_status()

    print("LLM HEALTH OK")

    print(r.json())


if __name__ == "__main__":

    run()