# dcbot — Discord bot + FastAPI dashboard.
#
# The code lives in the image at /app; ALL runtime state, secrets and local
# assets come from a bind mount (see docker-compose.yml), so the image stays
# stateless and rebuilds don't touch data. The bot reads everything by relative
# path (config.yaml, json/, api_key/, private/, logs/, cogs_local/) -> those
# resolve under /app once the volumes are overlaid.
# Pinned by digest on purpose: BuildKit re-resolves a bare tag against the
# registry on every build, so each upstream refresh of python:3.13-slim
# invalidated the apt layer below and turned a 10s rebuild into a 20min one.
# To bump: `docker pull python:3.13-slim` and copy the new RepoDigest here.
FROM python:3.13-slim@sha256:3dd7cc108ec1493442514f5c2a871af6af0ec31d768ff6e378a93340c3b3db5f

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Taipei

# Optional apt mirror for the main archive (security stays on deb.debian.org).
# Set it when deb.debian.org's CDN is slow from your network, e.g. in the
# compose project's .env: APT_MIRROR=debian.csie.ntu.edu.tw
ARG APT_MIRROR=

# ffmpeg: music playback. git: in-container git ops (!deploy / autodeploy).
# tzdata: correct local time for the scheduled tasks.
RUN if [ -n "$APT_MIRROR" ]; then \
        sed -i "s|^URIs: http://deb.debian.org/debian$|URIs: http://$APT_MIRROR/debian|" \
            /etc/apt/sources.list.d/debian.sources; \
    fi \
 && apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg git ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# cwd stays /app so the code's relative paths (os.listdir("cogs"), dashboard
# templates, leetcode import) resolve. The runtime data dirs (config.yaml,
# json/, api_key/, private/, logs/, cogs_local/) are overlaid into /app from
# the bind mount via compose volumes.
CMD ["python", "project.py"]
