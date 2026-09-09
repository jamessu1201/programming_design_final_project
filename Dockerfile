# dcbot — Discord bot + FastAPI dashboard.
#
# The code lives in the image at /app; ALL runtime state, secrets and local
# assets come from a bind mount (see docker-compose.yml), so the image stays
# stateless and rebuilds don't touch data. The bot reads everything by relative
# path (config.yaml, json/, api_key/, private/, logs/, cogs_local/) -> those
# resolve under /app once the volumes are overlaid.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Taipei

# ffmpeg: music playback. git: in-container git ops (!deploy / autodeploy).
# tzdata: correct local time for the scheduled tasks.
RUN apt-get update && apt-get install -y --no-install-recommends \
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
