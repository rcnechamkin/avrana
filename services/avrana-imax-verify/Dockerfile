# Avrana IMAX framing verifier.
#
# ffmpeg is the entire reason this is a container: the host has none, Radarr's image has none,
# and the only ffmpeg on the box belongs to Jellyfin (reaching into that container to borrow it
# would couple two unrelated services and add load to the one already doing transcoding).
FROM python:3.12-slim

# ffmpeg brings ffprobe with it. No Python dependencies: the verifier is stdlib only.
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY imax_verify.py server.py /app/

ENV IMAX_EXPECTATIONS=/config/expectations.json \
    IMAX_RESULTS=/config/results \
    PYTHONUNBUFFERED=1

EXPOSE 8099
CMD ["python3", "/app/server.py"]
