FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first (leverage Docker layer cache)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Add server code
COPY server.py ./

# Provide a default config (can be overridden by volume mount)
COPY config.example.toml ./config.toml

# Default: use /app/config.toml unless overridden by env var DB_MCP_CONFIG
ENV DB_MCP_CONFIG=/app/config.toml

# MCP runs over HTTP when MCP_TRANSPORT=streamable-http (see docker-compose)
CMD ["python", "server.py"]

