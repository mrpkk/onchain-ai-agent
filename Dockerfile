# KARTA demo server (public API + MCP). Used by catalog crawlers and local runs.
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN pip install --no-cache-dir fastapi==0.140.13 "uvicorn==0.51.0" cryptography mcp pydantic

COPY backend/src ./src

EXPOSE 8295
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8295/health',timeout=2)"
CMD ["python","-m","uvicorn","src.demo.app:app","--host","0.0.0.0","--port","8295"]
