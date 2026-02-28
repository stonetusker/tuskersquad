import yaml
from pathlib import Path
from typing import Dict


class ModelRouter:

    """
    Loads config/models.yaml.

    Agent → model mapping.
    """

    def __init__(self, config_path="config/models.yaml"):

        self.config_path = Path(config_path)

        self.models = self._load()

    def _load(self) -> Dict:

        if not self.config_path.exists():

            raise FileNotFoundError(
                "config/models.yaml missing"
            )

        with open(self.config_path, "r") as f:

            return yaml.safe_load(f)

    def get_model_config(self, agent: str) -> Dict:

        if agent not in self.models:

            raise ValueError(
                f"No model config for agent {agent}"
            )

        return self.models[agent]