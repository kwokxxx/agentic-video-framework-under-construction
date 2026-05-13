from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentic_llm.web.dev import has_changed, should_watch, snapshot_files


class WebDevReloadTest(unittest.TestCase):
    def test_snapshot_detects_watched_file_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "src" / "agentic_llm"
            source.mkdir(parents=True)
            file_path = source / "example.py"
            file_path.write_text("one", encoding="utf-8")

            first = snapshot_files(root)
            file_path.write_text("two", encoding="utf-8")
            second = snapshot_files(root)

            self.assertTrue(has_changed(first, second))

    def test_ignores_runtime_and_cache_files(self) -> None:
        self.assertFalse(should_watch(Path(".agentic_llm/history/demo.jsonl")))
        self.assertFalse(should_watch(Path("src/agentic_llm/__pycache__/x.pyc")))
        self.assertFalse(should_watch(Path("src/agentic_llm.egg-info/PKG-INFO")))
        self.assertTrue(should_watch(Path("src/agentic_llm/web/app.py")))
        self.assertTrue(should_watch(Path("src/agentic_llm/web/static/app.js")))
        self.assertTrue(should_watch(Path("AGENT.md")))
        self.assertTrue(should_watch(Path(".env")))


if __name__ == "__main__":
    unittest.main()

