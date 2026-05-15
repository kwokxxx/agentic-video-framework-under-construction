from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import json
from pathlib import Path
import time
from typing import Any, Awaitable, Callable
import uuid


CronExecutor = Callable[["CronJob"], Awaitable[None]]


@dataclass(slots=True)
class CronSchedule:
    kind: str
    run_at_ms: int | None = None
    expr: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "run_at_ms": self.run_at_ms,
            "expr": self.expr,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CronSchedule":
        return cls(
            kind=str(payload.get("kind") or "once"),
            run_at_ms=_as_optional_int(payload.get("run_at_ms")),
            expr=str(payload.get("expr")) if payload.get("expr") is not None else None,
        )


@dataclass(slots=True)
class CronState:
    next_run_at_ms: int | None = None
    last_run_at_ms: int | None = None
    run_count: int = 0
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "next_run_at_ms": self.next_run_at_ms,
            "last_run_at_ms": self.last_run_at_ms,
            "run_count": self.run_count,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CronState":
        return cls(
            next_run_at_ms=_as_optional_int(payload.get("next_run_at_ms")),
            last_run_at_ms=_as_optional_int(payload.get("last_run_at_ms")),
            run_count=int(payload.get("run_count") or 0),
            last_error=str(payload.get("last_error")) if payload.get("last_error") else None,
        )


@dataclass(slots=True)
class CronJob:
    id: str
    description: str
    prompt: str
    session_id: str
    enabled: bool
    schedule: CronSchedule
    state: CronState = field(default_factory=CronState)
    delete_after_run: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "description": self.description,
            "prompt": self.prompt,
            "session_id": self.session_id,
            "enabled": self.enabled,
            "schedule": self.schedule.to_dict(),
            "state": self.state.to_dict(),
            "delete_after_run": self.delete_after_run,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CronJob":
        return cls(
            id=str(payload["id"]),
            description=str(payload.get("description") or ""),
            prompt=str(payload.get("prompt") or payload.get("description") or ""),
            session_id=str(payload.get("session_id") or "default"),
            enabled=bool(payload.get("enabled", True)),
            schedule=CronSchedule.from_dict(payload.get("schedule") or {}),
            state=CronState.from_dict(payload.get("state") or {}),
            delete_after_run=bool(payload.get("delete_after_run", True)),
            metadata=dict(payload.get("metadata") or {}),
        )


class CronJobStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def list_jobs(self) -> list[CronJob]:
        if not self.path.exists():
            return []
        payload = json.loads(self.path.read_text(encoding="utf-8") or "[]")
        if not isinstance(payload, list):
            raise ValueError("Cron job store must contain a JSON list")
        return [CronJob.from_dict(item) for item in payload if isinstance(item, dict)]

    def save_jobs(self, jobs: list[CronJob]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps([job.to_dict() for job in jobs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def upsert(self, job: CronJob) -> None:
        jobs = self.list_jobs()
        for index, existing in enumerate(jobs):
            if existing.id == job.id:
                jobs[index] = job
                self.save_jobs(jobs)
                return
        jobs.append(job)
        self.save_jobs(jobs)

    def delete(self, job_id: str) -> bool:
        jobs = self.list_jobs()
        kept = [job for job in jobs if job.id != job_id]
        self.save_jobs(kept)
        return len(kept) != len(jobs)

    def get(self, job_id: str) -> CronJob | None:
        for job in self.list_jobs():
            if job.id == job_id:
                return job
        return None


class CronScheduler:
    def __init__(self, *, store: CronJobStore, executor: CronExecutor) -> None:
        self._store = store
        self._executor = executor
        self._timer_task: asyncio.Task[None] | None = None
        self._running = False

    def start(self) -> None:
        self._running = True
        self.arm_timer()

    def stop(self) -> None:
        self._running = False
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None

    def arm_timer(self) -> None:
        if not self._running:
            return
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None
        next_wake = self.get_next_wake_ms()
        if next_wake is None:
            return
        delay_s = max(0, next_wake - _now_ms()) / 1000
        self._timer_task = asyncio.create_task(self._tick(delay_s))

    def get_next_wake_ms(self) -> int | None:
        times = [
            job.state.next_run_at_ms
            for job in self._store.list_jobs()
            if job.enabled and job.state.next_run_at_ms is not None
        ]
        return min(times) if times else None

    async def _tick(self, delay_s: float) -> None:
        try:
            await asyncio.sleep(delay_s)
            if self._running:
                await self.on_timer()
        except asyncio.CancelledError:
            return

    async def on_timer(self) -> None:
        jobs = self._store.list_jobs()
        now = _now_ms()
        due_jobs = [
            job
            for job in jobs
            if job.enabled
            and job.state.next_run_at_ms is not None
            and job.state.next_run_at_ms <= now
        ]
        changed = False
        for job in due_jobs:
            await self._execute_job(job)
            changed = True
            if job.schedule.kind in {"once", "at"}:
                if job.delete_after_run:
                    jobs = [candidate for candidate in jobs if candidate.id != job.id]
                else:
                    job.enabled = False
                    job.state.next_run_at_ms = None
            elif job.schedule.kind == "cron":
                job.state.next_run_at_ms = compute_next_run_ms(job.schedule, _now_ms())

        if changed:
            self._store.save_jobs(jobs)
        self.arm_timer()

    async def _execute_job(self, job: CronJob) -> None:
        job.state.last_run_at_ms = _now_ms()
        job.state.run_count += 1
        try:
            await self._executor(job)
            job.state.last_error = None
        except Exception as exc:
            job.state.last_error = f"{type(exc).__name__}: {exc}"


def create_cron_job(
    *,
    description: str,
    prompt: str,
    session_id: str,
    schedule: CronSchedule,
    enabled: bool = True,
    delete_after_run: bool = True,
    metadata: dict[str, Any] | None = None,
) -> CronJob:
    if schedule.kind in {"once", "at"} and schedule.run_at_ms is None:
        raise ValueError("once/at schedules require run_at_ms")
    if schedule.kind == "cron" and not schedule.expr:
        raise ValueError("cron schedules require expr")
    next_run_at_ms = compute_next_run_ms(schedule, _now_ms())
    return CronJob(
        id=uuid.uuid4().hex,
        description=description,
        prompt=prompt,
        session_id=session_id,
        enabled=enabled,
        schedule=schedule,
        state=CronState(next_run_at_ms=next_run_at_ms),
        delete_after_run=delete_after_run,
        metadata=metadata or {},
    )


def compute_next_run_ms(schedule: CronSchedule, now_ms: int) -> int | None:
    if schedule.kind in {"once", "at"}:
        return schedule.run_at_ms
    if schedule.kind != "cron" or not schedule.expr:
        return None
    return _compute_next_simple_cron(schedule.expr, now_ms)


def _compute_next_simple_cron(expr: str, now_ms: int) -> int:
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError("cron expr must contain five fields")
    minute_expr, hour_expr, day_expr, month_expr, weekday_expr = parts
    if day_expr != "*" or month_expr != "*" or weekday_expr != "*":
        raise ValueError("simple cron supports only '*' for day/month/weekday")

    start = int(now_ms / 1000) + 60
    candidate = start - (start % 60)
    end = candidate + 366 * 24 * 60 * 60
    while candidate <= end:
        local = time.localtime(candidate)
        if _matches_field(local.tm_min, minute_expr, 0, 59) and _matches_field(local.tm_hour, hour_expr, 0, 23):
            return candidate * 1000
        candidate += 60
    raise ValueError("could not compute next cron run")


def _matches_field(value: int, expr: str, min_value: int, max_value: int) -> bool:
    if expr == "*":
        return True
    if expr.startswith("*/"):
        step = int(expr[2:])
        if step <= 0:
            raise ValueError("cron step must be positive")
        return (value - min_value) % step == 0
    expected = int(expr)
    if expected < min_value or expected > max_value:
        raise ValueError("cron field out of range")
    return value == expected


def _as_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _now_ms() -> int:
    return int(time.time() * 1000)
