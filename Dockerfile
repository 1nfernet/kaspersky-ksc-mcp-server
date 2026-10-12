FROM python:3.14-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
ENV KSC_PORT=13299 KSC_VERIFY=false KSC_TIMEOUT=30
EXPOSE 8000
# GET /mcp antwortet mit 400 (POST-only) — das beweist: Server lebt und
# MCP-Layer antwortet. Gilt für mcp==2.3.0 (gepinnt via pyproject).
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD sh -c 'code=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/mcp); [ "$code" = "400" ]'
CMD ["python", "-m", "ksc_mcp.server", "--http", "--port", "8000", "--host", "0.0.0.0"]
