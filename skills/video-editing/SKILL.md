---
name: video-editing
description: "Use when the user asks for intelligent video editing, clip planning, media preparation, rough cut orchestration, rendering, or publishing preparation. This skill coordinates file tools, MCP audio/video services, checkpoints, and subagents when tasks are long-running."
always: false
---

# Video Editing Skill

Use this SOP when the task is about planning or executing an intelligent video editing flow.

## Workflow

1. Clarify the deliverable: script only, editing plan, rendered asset, or publishing package.
2. Inspect available project files and media references before inventing missing assets.
3. If media is missing, prepare a search or material collection step before rendering.
4. Convert the user goal into an edit plan: narrative, shot order, captions, audio, visual treatment, duration, and output constraints.
5. Use MCP tools for stored audio/video services when they are registered. Prefer MCP render/material tools over ad hoc local simulation.
6. For long-running research, media grouping, or render preparation, use `spawn_subagent` so the main interaction can continue.
7. Use checkpointed tool results as the source of truth after each completed tool call.
8. Return a concise final package: plan, generated artifacts, unresolved blockers, and next action.

## Constraints

- Do not claim a video was rendered unless a render tool or MCP service returned a concrete artifact.
- Do not publish or schedule publishing unless the user asked for it and the relevant tool confirms the job.
- Keep tool observations separate from final user-facing copy.
- If a render or media MCP tool is unavailable, explain the missing capability and provide the reproducible edit plan instead.
