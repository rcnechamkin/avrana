# Avrana portal — tiny stdlib server rendering the role-aware front door. No third-party deps.
FROM python:3.12-slim@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8095
COPY portal.py /app/portal.py
WORKDIR /app
USER 1000:1000
EXPOSE 8095
HEALTHCHECK --interval=30s --timeout=4s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8095/healthz',timeout=3).status==200 else 1)"
CMD ["python3", "/app/portal.py"]
