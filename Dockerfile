# syntax=docker/dockerfile:1
FROM python:3.11-slim

# Install uv (package manager)
RUN curl -LsSf https://astral.sh/uv/install.sh | sh

WORKDIR /app
COPY . /app

# Install Python deps via uv lock (if present) else via pyproject
RUN uv pip sync --system

ENV PYTHONUNBUFFERED=1
CMD ["python", "scripts/start_dev.py"] 