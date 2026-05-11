FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt setup.py ./
COPY agent_manager/ ./agent_manager/

RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] jinja2 sse-starlette python-multipart httpx \
    -r requirements.txt \
    -e .

COPY agents/ ./agents/

ENV AGENTMGR_AGENTS_DIR=agents

EXPOSE 8000

CMD ["uvicorn", "agent_manager.web.app:app", "--host", "0.0.0.0", "--port", "8000"]
