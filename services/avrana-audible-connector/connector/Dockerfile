# Avrana Audible Connector — public-facing web tier (server-rendered FastAPI).
# Runs as a non-root user; holds no Audible credentials and never shells to Libation.
# Digest-pinned (python:3.12-slim as of 2026-08-14) to match the repo's pinning convention.
# To refresh: `docker pull python:3.12-slim` then update the digest below.
FROM python:3.12-slim@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# uid/gid 1000 matches the host owner (cody) and the mounted /data volume.
RUN useradd -u 1000 -m appuser && mkdir -p /data && chown -R appuser:appuser /data /app
USER appuser

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3).status==200 else 1)"

CMD ["uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
