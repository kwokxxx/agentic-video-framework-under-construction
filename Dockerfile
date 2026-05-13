FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY pyproject.toml README.md AGENT.md USER.md TOOLS.md ./
COPY src ./src

RUN python -m pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["python", "-m", "agentic_llm.web.dev", "--host", "0.0.0.0", "--port", "8000"]
