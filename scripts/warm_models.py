import subprocess

models = [
    "qwen2.5:14b",
    "deepseek-coder:6.7b"
]

for model in models:
    print(f"Pulling {model}")
    subprocess.run(["ollama", "pull", model])
