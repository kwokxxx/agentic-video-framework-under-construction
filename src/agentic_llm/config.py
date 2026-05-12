from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True, slots=True)
class DeepSeekSettings:
    api_key: str | None
    base_url: str
    model: str

    @classmethod
    def from_env(cls) -> "DeepSeekSettings":
        return cls(
            api_key=os.environ.get("DEEPSEEK_API_KEY"),
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-pro"),
        )

