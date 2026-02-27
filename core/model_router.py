import yaml
from pathlib import Path
from typing import Dict


class ModelRouter:
    """
    Loads and routes model configuration per agent.
    """

    def __init__(self, config_path: str = "config/models.yaml"):
        self.config_path = Path(config_path)
        self.models = self._load_config()

    def _load_config(self) -> Dict:
        if not self.config_path.exists():
            raise FileNotFoundError("models.yaml not found")
        with open(self.config_path, "r") as f:
            return yaml.safe_load(f)

    def get_model_config(self, agent_name: str) -> Dict:
        if agent_name not in self.models:
            raise ValueError(f"No model config found for agent: {agent_name}")
        return self.models[agent_name]
