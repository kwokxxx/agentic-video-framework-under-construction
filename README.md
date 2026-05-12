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

Set the DeepSeek API key through the environment. Do not write the key into source files or logs.

```bash
export DEEPSEEK_API_KEY="..."
export DEEPSEEK_BASE_URL="https://api.deepseek.com"
export DEEPSEEK_MODEL="deepseek-v4-pro"
```

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

