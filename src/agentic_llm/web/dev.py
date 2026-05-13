from __future__ import annotations

import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


WATCH_SUFFIXES = {".py", ".html", ".css", ".js", ".md", ".toml"}
WATCH_FILENAMES = {
    ".env",
    "Dockerfile",
    "AGENT.md",
    "USER.md",
    "TOOLS.md",
    "README.md",
    "pyproject.toml",
}
IGNORED_DIRS = {
    ".agentic_llm",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    "docs",
}


def should_watch(path: Path) -> bool:
    if any(part in IGNORED_DIRS for part in path.parts):
        return False
    if path.name.endswith(".egg-info"):
        return False
    return path.name in WATCH_FILENAMES or path.suffix in WATCH_SUFFIXES


def snapshot_files(root: Path) -> dict[str, int]:
    snapshot: dict[str, int] = {}
    for path in root.rglob("*"):
        if not path.is_file() or not should_watch(path.relative_to(root)):
            continue
        try:
            snapshot[str(path.relative_to(root))] = path.stat().st_mtime_ns
        except FileNotFoundError:
            continue
    return snapshot


def has_changed(previous: dict[str, int], current: dict[str, int]) -> bool:
    return previous != current


def start_server(host: str, port: int, root: Path) -> subprocess.Popen[bytes]:
    env = os.environ.copy()
    src_path = str(root / "src")
    env["PYTHONUNBUFFERED"] = "1"
    env["PYTHONPATH"] = (
        src_path
        if not env.get("PYTHONPATH")
        else f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    )
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "agentic_llm.web.app",
            "--host",
            host,
            "--port",
            str(port),
        ],
        cwd=root,
        env=env,
    )


def stop_server(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.send_signal(signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def run_dev_server(
    *,
    host: str,
    port: int,
    workspace_root: Path,
    interval: float = 1.0,
) -> None:
    root = workspace_root.resolve()
    previous = snapshot_files(root)
    process = start_server(host, port, root)
    print(
        f"Hot reload enabled. Watching {root}. "
        f"Open http://{host}:{port}"
    )

    try:
        while True:
            time.sleep(interval)
            if process.poll() is not None:
                print("Web server exited; restarting.")
                process = start_server(host, port, root)
                previous = snapshot_files(root)
                continue

            current = snapshot_files(root)
            if has_changed(previous, current):
                print("Change detected; restarting web server.")
                stop_server(process)
                process = start_server(host, port, root)
                previous = current
    except KeyboardInterrupt:
        pass
    finally:
        stop_server(process)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--interval", type=float, default=1.0)
    args = parser.parse_args()
    run_dev_server(
        host=args.host,
        port=args.port,
        workspace_root=Path.cwd(),
        interval=args.interval,
    )


if __name__ == "__main__":
    main()

