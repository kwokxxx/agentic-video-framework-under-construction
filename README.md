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

Create a local `.env` file in the project root, then fill in your DeepSeek API key. Do not commit `.env` or write the key into source files or logs.

```text
DEEPSEEK_API_KEY=your_deepseek_api_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

Use `deepseek-v4-flash` first to keep smoke tests cheap. Switch to `deepseek-v4-pro` when quality matters more than cost.

Bootstrap files live at the workspace root:

```text
AGENT.md  # agent role, architecture awareness, operating constraints
USER.md   # stable user and project preferences
TOOLS.md  # tool usage notes and current tool gaps
```

The runtime loads these files into the system prompt on every run. If one is absent, the runtime skips it and continues.

## Run

```bash
python3 -m agentic_llm "Read README.md and summarize it."
```

## Web Console

Start the local project console with hot reload:

```bash
python3 -m agentic_llm.web.dev --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`.

The dev runner watches Python files, web static files, `.env`, and Bootstrap files. When they change, it restarts the inner web server. Refresh the browser after front-end changes.

The console has two views:

- User: normal Agent usage through the current MQ and Agent loop.
- Developer: runtime status, MQ flow, session routing, LLM iteration events, tool execution events, and persistence traces.

Runtime state is written under `.agentic_llm/`:

```text
.agentic_llm/history/
.agentic_llm/checkpoints/
```

## Docker

For development, use Docker Compose. It builds the image, loads `.env`, mounts the project into `/app`, and runs the hot reload server:

```bash
docker compose up --build
```

Open `http://localhost:8000`.

After the first build, use this for normal development:

```bash
docker compose up
```

The Compose service watches Python files, front-end files, `.env`, and Bootstrap files. When they change, it restarts the inner web server. Refresh the browser after front-end changes.

Use plain Docker only when you want to run the image without Compose:

```bash
docker build -t agentic-video-framework .
docker run --env-file .env -p 8000:8000 -v "$(pwd):/app" agentic-video-framework
```

Rebuild only when `Dockerfile`, `pyproject.toml`, or dependency installation changes.

## Test

The test suite uses a fake LLM provider and does not call DeepSeek:

```bash
python3 -m unittest discover -s tests
```
