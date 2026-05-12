from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_llm.config import DeepSeekSettings


class DeepSeekSettingsTest(unittest.TestCase):
    def test_loads_dotenv_from_current_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "\n".join(
                    [
                        "DEEPSEEK_API_KEY=test-key",
                        "DEEPSEEK_BASE_URL=https://example.test",
                        "DEEPSEEK_MODEL=deepseek-v4-pro",
                    ]
                ),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                with patch.object(Path, "cwd", return_value=root):
                    settings = DeepSeekSettings.from_env()

            self.assertEqual(settings.api_key, "test-key")
            self.assertEqual(settings.base_url, "https://example.test")
            self.assertEqual(settings.model, "deepseek-v4-pro")

    def test_environment_overrides_dotenv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "DEEPSEEK_API_KEY=file-key\nDEEPSEEK_MODEL=deepseek-v4-flash\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key"}, clear=True):
                with patch.object(Path, "cwd", return_value=root):
                    settings = DeepSeekSettings.from_env()

            self.assertEqual(settings.api_key, "env-key")
            self.assertEqual(settings.model, "deepseek-v4-flash")


if __name__ == "__main__":
    unittest.main()
