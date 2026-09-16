import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    sessions: Path
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    model: str = ""

    @classmethod
    def load(cls, sessions=None):
        load_dotenv(ROOT / ".env")
        root = Path(sessions or os.getenv("RESEARCHFLOW_SESSIONS", "sessions"))
        if not root.is_absolute():
            root = ROOT / root
        return cls(
            root.resolve(),
            os.getenv("MODEL_API_KEY", ""),
            os.getenv("MODEL_BASE_URL", "https://api.openai.com/v1"),
            os.getenv("MODEL_NAME", ""),
        )

    def require_model(self):
        if not self.api_key or not self.model:
            raise ValueError("请在 .env 填写 MODEL_API_KEY 和 MODEL_NAME。")
