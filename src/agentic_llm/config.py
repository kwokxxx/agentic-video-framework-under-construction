from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True, slots=True)
class DeepSeekSettings:
    api_key: str | None
    base_url: str
    model: str

    @classmethod
    def from_env(cls) -> "DeepSeekSettings":
        dotenv = _load_dotenv(Path.cwd() / ".env")
        return cls(
            api_key=_get_config("DEEPSEEK_API_KEY", dotenv),
            base_url=_get_config(
                "DEEPSEEK_BASE_URL",
                dotenv,
                default="https://api.deepseek.com",
            ),
            model=_get_config("DEEPSEEK_MODEL", dotenv, default="deepseek-v4-flash"),
        )


def _get_config(
    key: str,
    dotenv: dict[str, str],
    *,
    default: str | None = None,
) -> str | None:
    return os.environ.get(key) or dotenv.get(key) or default


def _load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values
