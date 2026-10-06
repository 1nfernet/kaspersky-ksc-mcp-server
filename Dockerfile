FROM python:3.14-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
ENV KSC_PORT=13299 KSC_VERIFY=false KSC_TIMEOUT=30
EXPOSE 8000
CMD ["python", "-m", "ksc_mcp.server", "--http", "--port", "8000", "--host", "0.0.0.0"]
