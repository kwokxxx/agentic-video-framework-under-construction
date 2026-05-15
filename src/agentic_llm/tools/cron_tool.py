from __future__ import annotations

import time
from typing import Any

from agentic_llm.runtime.cron import (
    CronJobStore,
    CronSchedule,
    create_cron_job,
)
from agentic_llm.tools.base import BaseTool, ToolResult


class CronTool(BaseTool):
    name = "cron_job"
    description = "Create, list, read, update, or delete filesystem-backed Cron jobs."
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "description": "One of create, list, read, update, delete.",
                "enum": ["create", "list", "read", "update", "delete"],
            },
            "id": {
                "type": "string",
                "description": "Cron job id for read, update, or delete.",
            },
            "description": {
                "type": "string",
                "description": "Human readable job description.",
            },
            "prompt": {
                "type": "string",
                "description": "Prompt to send back into the main Agent when the job is due.",
            },
            "session_id": {
                "type": "string",
                "description": "Session id that should receive the due job message.",
            },
            "enabled": {
                "type": "boolean",
                "description": "Whether the job is enabled.",
            },
            "schedule": {
                "type": "object",
                "description": "Schedule object. Use kind=once/at with run_at_ms, or kind=cron with expr.",
            },
        },
        "required": ["action"],
    }

    def __init__(self, store: CronJobStore, *, on_change: Any | None = None) -> None:
        self._store = store
        self._on_change = on_change

    @property
    def exclusive(self) -> bool:
        return True

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        action = arguments.get("action")
        if action == "create":
            result = self._create(arguments)
            self._notify_changed()
            return result
        if action == "list":
            jobs = [job.to_dict() for job in self._store.list_jobs()]
            return ToolResult(self.name, _format_json(jobs), metadata={"jobs": len(jobs)})
        if action == "read":
            job_id = _require_string(arguments, "id")
            job = self._store.get(job_id)
            if job is None:
                raise ValueError(f"Cron job not found: {job_id}")
            return ToolResult(self.name, _format_json(job.to_dict()), metadata={"id": job_id})
        if action == "delete":
            job_id = _require_string(arguments, "id")
            deleted = self._store.delete(job_id)
            self._notify_changed()
            return ToolResult(self.name, f"deleted={deleted}", metadata={"id": job_id, "deleted": deleted})
        if action == "update":
            result = self._update(arguments)
            self._notify_changed()
            return result
        raise ValueError("action must be one of create, list, read, update, delete")

    def _create(self, arguments: dict[str, Any]) -> ToolResult:
        schedule = _parse_schedule(arguments.get("schedule"))
        description = str(arguments.get("description") or arguments.get("prompt") or "").strip()
        prompt = str(arguments.get("prompt") or description).strip()
        if not description:
            raise ValueError("description is required for create")
        if not prompt:
            raise ValueError("prompt is required for create")
        job = create_cron_job(
            description=description,
            prompt=prompt,
            session_id=str(arguments.get("session_id") or "default"),
            schedule=schedule,
            enabled=bool(arguments.get("enabled", True)),
        )
        self._store.upsert(job)
        return ToolResult(
            self.name,
            f"Created cron job {job.id}; next_run_at_ms={job.state.next_run_at_ms}.",
            metadata=job.to_dict(),
        )

    def _update(self, arguments: dict[str, Any]) -> ToolResult:
        job_id = _require_string(arguments, "id")
        job = self._store.get(job_id)
        if job is None:
            raise ValueError(f"Cron job not found: {job_id}")
        if "description" in arguments:
            job.description = str(arguments["description"])
        if "prompt" in arguments:
            job.prompt = str(arguments["prompt"])
        if "session_id" in arguments:
            job.session_id = str(arguments["session_id"])
        if "enabled" in arguments:
            job.enabled = bool(arguments["enabled"])
        if "schedule" in arguments:
            job.schedule = _parse_schedule(arguments.get("schedule"))
            from agentic_llm.runtime.cron import compute_next_run_ms

            job.state.next_run_at_ms = compute_next_run_ms(job.schedule, int(time.time() * 1000))
        self._store.upsert(job)
        return ToolResult(self.name, f"Updated cron job {job.id}.", metadata=job.to_dict())

    def _notify_changed(self) -> None:
        if self._on_change is not None:
            self._on_change()


def _parse_schedule(value: Any) -> CronSchedule:
    if not isinstance(value, dict):
        raise ValueError("schedule must be an object")
    return CronSchedule.from_dict(value)


def _require_string(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _format_json(value: Any) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, indent=2)
