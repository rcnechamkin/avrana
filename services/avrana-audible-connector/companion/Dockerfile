# Avrana Libation Companion — a thin per-profile HTTP adapter over LibationCli.
#
# Built FROM the same pinned rmcrackan/libation digest already proven on this host
# (v13.7.7). Do NOT replace the digest with a floating tag. Libation is GPL-3.0; this
# adapter only invokes the shipped LibationCli as a separate process and adds an HTTP
# layer. See LICENSES/ and THIRD_PARTY_NOTICES.md.
FROM rmcrackan/libation@sha256:a1b4a10150d785ddbb3359ccb0cfd089abd2a462330d30ffb68b638e8d3ad6d6

USER root
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 python3-pip python3-venv curl \
 && rm -rf /var/lib/apt/lists/*

# Isolated venv so we never touch the base image's runtime.
RUN python3 -m venv /opt/companion-venv \
 && /opt/companion-venv/bin/pip install --no-cache-dir \
      fastapi==0.115.6 "uvicorn[standard]==0.34.0"
ENV PATH="/opt/companion-venv/bin:${PATH}"

COPY api /opt/companion/api
COPY LICENSES /opt/companion/LICENSES
COPY THIRD_PARTY_NOTICES.md /opt/companion/THIRD_PARTY_NOTICES.md

# Runs as uid/gid 1000 (matches the host owner and the /data + /profiles volumes).
RUN mkdir -p /profiles /control && chown -R 1000:1000 /profiles /opt/companion
USER 1000:1000

ENV PROFILES_ROOT=/profiles \
    LIBATION_BOOKS_DIR=/data \
    COMPANION_TOKEN_FILE=/control/token \
    LIBATION_CREATE_DB=true

WORKDIR /opt/companion
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/health || exit 1

# Override the base image's Libation scan loop: run the companion API instead.
ENTRYPOINT []
CMD ["uvicorn", "api.companion:app", "--host", "0.0.0.0", "--port", "8080"]
