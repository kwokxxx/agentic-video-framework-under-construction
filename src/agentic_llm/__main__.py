from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from agentic_llm.agent_loop import AgentOnceRun
from agentic_llm.context import ContextBuilder
from agentic_llm.llm import DeepSeekProvider
from agentic_llm.memory import MarkdownMemoryStore
from agentic_llm.mq import AgentMainLoop, InboundMessage, InMemoryMessageQueue
from agentic_llm.runtime import CheckpointStore, CompositeHook, CronJobStore
from agentic_llm.session import JsonlHistoryStore
from agentic_llm.skills import SkillLoader
from agentic_llm.subagents import SubAgentManager
from agentic_llm.tools import (
    CronTool,
    EditFileTool,
    FetchUrlTool,
    GrepFileTool,
    ReadFileTool,
    ReadSkillTool,
    RewriteMemoryTool,
    SearchWebTool,
    SpawnTool,
    ToolRegistry,
    WriteFileTool,
)


async def _run(prompt: str, session_id: str, workspace_root: Path) -> None:
    state_root = workspace_root / ".agentic_llm"
    history_store = JsonlHistoryStore(state_root / "history")
    checkpoint_store = CheckpointStore(state_root / "checkpoints")
    skill_loader = SkillLoader(workspace_root=workspace_root)
    memory_store = MarkdownMemoryStore(workspace_root)
    cron_store = CronJobStore(state_root / "cron" / "jobs.json")
    provider = DeepSeekProvider()

    def build_agent(*, include_spawn: bool) -> AgentOnceRun:
        context_builder = ContextBuilder(
            workspace_root=workspace_root,
            history_store=history_store,
            skill_loader=skill_loader,
        )
        tools = [
            ReadFileTool(workspace_root),
            GrepFileTool(workspace_root),
            WriteFileTool(workspace_root),
            EditFileTool(workspace_root),
            SearchWebTool(),
            FetchUrlTool(),
            ReadSkillTool(skill_loader),
            RewriteMemoryTool(memory_store),
            CronTool(cron_store),
        ]
        if include_spawn:
            tools.append(SpawnTool(subagent_manager))
        return AgentOnceRun(
            provider=provider,
            context_builder=context_builder,
            tool_registry=ToolRegistry(tools),
            history_store=history_store,
            checkpoint_store=checkpoint_store,
            hook=CompositeHook(),
        )

    subagent_manager = SubAgentManager(
        agent_factory=lambda: build_agent(include_spawn=False)
    )
    agent = build_agent(include_spawn=True)
    queue = InMemoryMessageQueue()
    main_loop = AgentMainLoop(queue=queue, agent=agent)
    await queue.publish_inbound(
        InboundMessage(session_id=session_id, content=prompt)
    )
    await main_loop.process_once()
    outbound = await queue.consume_outbound()
    queue.acknowledge_outbound()
    if outbound.content:
        print(outbound.content)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("prompt")
    parser.add_argument("--session-id", default="default")
    args = parser.parse_args()
    asyncio.run(_run(args.prompt, args.session_id, Path.cwd()))


if __name__ == "__main__":
    main()
