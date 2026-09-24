# Stdlib only, so there is nothing to install and no dependency surface.
FROM python:3.12-slim@sha256:dd29372629eeba2dd003fd9e9d35a5b8236c44727875a0364254b5127af88e65

WORKDIR /app
COPY kindle.py /app/kindle.py

USER 1000:1000
EXPOSE 8096
CMD ["python3", "-u", "/app/kindle.py"]
