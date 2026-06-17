# dcbot — Discord bot + FastAPI dashboard. Runs in the CT108 docker farm.
#
# The code lives in the image at /app; ALL runtime state, secrets and local
# assets come from the HDD bind mount at /data (which is also WORKDIR), so the
# image stays stateless and rebuilds don't touch data. The bot reads everything
# by relative path (config.yaml, json/, api_key/, private/, logs/, ur_noob.png,
# chrome-linux64/, chromedriver-linux64/) -> those resolve under /data.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Asia/Taipei

# ffmpeg: music playback. git: in-container git ops. tzdata: correct local time
# for the scheduled tasks. (Chrome/chromedriver runtime libs come from the
# `playwright install --with-deps` step below.)
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg git ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt \
 && python -m playwright install --with-deps chromium

COPY . .

# cwd stays /app so the code's relative paths (os.listdir("cogs"), dashboard
# templates, leetcode/attend_* imports) resolve. The runtime data dirs
# (config.yaml, json/, api_key/, private/, logs/) are overlaid into /app from
# the /data bind mount via compose volumes.
CMD ["python", "project.py"]
