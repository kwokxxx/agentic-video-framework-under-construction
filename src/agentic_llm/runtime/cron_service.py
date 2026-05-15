from __future__ import annotations

import asyncio
import threading

from agentic_llm.runtime.cron import CronExecutor, CronJobStore, CronScheduler


class ThreadedCronService:
    """Runs CronScheduler in a background event loop so timers do not block Agent QA."""

    def __init__(self, *, store: CronJobStore, executor: CronExecutor) -> None:
        self._store = store
        self._executor = executor
        self._loop: asyncio.AbstractEventLoop | None = None
        self._scheduler: CronScheduler | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, name="cron-scheduler", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=5)

    def stop(self) -> None:
        if self._loop is None:
            return
        self._loop.call_soon_threadsafe(self._stop_loop)

    def arm_timer(self) -> None:
        if self._loop is None or self._scheduler is None:
            return
        self._loop.call_soon_threadsafe(self._scheduler.arm_timer)

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._scheduler = CronScheduler(store=self._store, executor=self._executor)
        self._scheduler.start()
        self._ready.set()
        loop.run_forever()
        self._scheduler.stop()
        loop.close()

    def _stop_loop(self) -> None:
        if self._scheduler is not None:
            self._scheduler.stop()
        if self._loop is not None:
            self._loop.stop()
