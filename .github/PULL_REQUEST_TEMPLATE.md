## What this changes

<!-- One or two sentences. Link an issue if there is one. -->

## How it was tested

<!-- e.g. "ran the bot on a scratch server, /points top paginates correctly" -->

## Checklist

- [ ] `python -m compileall -q -x '(^|/)venv/' .` passes
- [ ] No secrets or runtime state committed (`config.yaml`, `api_key/`,
      `private/`, `json/points.json`, `json/queues.json`, `json/fb_watch.json`,
      `logs/`, `cogs_local/`)
- [ ] No hardcoded channel / role / guild IDs or hostnames — new settings added
      to `config.example.yaml` instead
- [ ] README updated if commands or setup steps changed
