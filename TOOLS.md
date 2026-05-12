# Tool Notes

## General Tool Policy

- Tool schemas are provided separately through ToolRegistry.
- This file records usage guidance and non-obvious constraints for the model.
- Tool results are observations. They should be interpreted before producing the final answer.
- If a tool fails, use the error as an observation and decide whether to retry, ask the user, or produce a partial answer.
- Do not call tools just to appear active. Use them when they reduce uncertainty or provide required local context.

## Current Tools

### read_file

Use `read_file` when the task requires reading a specific workspace file.

Constraints:

- The path must stay inside the workspace.
- Prefer workspace-relative paths.
- Use `max_chars` when the file may be large.
- Do not treat raw file content as the final answer; summarize or use it to answer the user.

### grep_file

Use `grep_file` when the task requires finding lines matching a pattern inside a specific workspace file.

Constraints:

- The path must stay inside the workspace.
- The pattern is a regular expression.
- Use `max_matches` when a file may have many matches.
- Prefer `grep_file` before `read_file` when only a small part of a large file is relevant.

## Tool Gaps

The runtime does not yet include:

- Write or edit tools.
- Web search or fetch tools.
- MCP tools.
- CronTool.
- SpawnTool or real SubAgent execution.
- Video editing or rendering tools.

When a user requests one of these missing capabilities, explain the gap and suggest the next implementation step instead of pretending the tool exists.

