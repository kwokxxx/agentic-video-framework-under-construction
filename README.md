# Agentic LLM

Minimal code scaffold for the Agentic LLM design recorded in `docs/agentic-llm-design-notes.md`.

The first implementation focuses on the smallest runnable loop:

```text
User prompt
-> ContextBuilder
-> DeepSeekProvider
-> ToolRegistry
-> Tool execution
-> Tool result returned to the model
-> Final answer
-> JSONL history
```

## Setup

Install the package in editable mode:

```bash
python3 -m pip install -e .
```

Create a local `.env` file from `.env.example`, then fill in your DeepSeek API key. Do not commit `.env` or write the key into source files or logs.

```bash
cp .env.example .env
```

Use `deepseek-v4-flash` first to keep smoke tests cheap. Switch to `deepseek-v4-pro` when quality matters more than cost.

Optional bootstrap files can be placed at the workspace root:

```text
AGENT.md
USER.md
TOOLS.md
```

If they are absent, the runtime uses a minimal system prompt and continues.

## Run

```bash
python3 -m agentic_llm "Read README.md and summarize it."
```

Runtime state is written under `.agentic_llm/`:

```text
.agentic_llm/history/
.agentic_llm/checkpoints/
```

## Test

The test suite uses a fake LLM provider and does not call DeepSeek:

```bash
python3 -m unittest discover -s tests
```
