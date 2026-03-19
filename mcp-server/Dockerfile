FROM --platform=linux/amd64 python:3.12-slim

# Install uv for fast dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy the mcp package
COPY mcp/ ./mcp/

# Install dependencies using uv
RUN uv pip install --system ./mcp/

# Environment defaults (overridden by ECS task definition)
ENV ALS_MCP_HOST=0.0.0.0
ENV ALS_MCP_PORT=8000

EXPOSE 8000

# Health check: hit the /health endpoint
HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=15s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1

# Run the MCP server in SSE mode
CMD ["als-mcp", "--sse"]
