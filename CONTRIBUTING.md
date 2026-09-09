# Contributing

Thanks for taking a look. PRs and issues are both welcome. 中英文都可以。

## Getting set up

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

You'll need your own Discord bot token in `api_key/token.txt` (or the
`bot_token` env var) and your own user ID in `private/owners.txt`. Test against
a scratch server rather than a real one — several features write state per
guild.

```bash
python project.py
```

## Before you open a PR

- **`python -m compileall -q -x '(^|/)venv/' .` must pass.** CI runs exactly
  this: the bot hot-reloads changed cogs in production within ~30s of a push to
  `main`, so a syntax error ships almost immediately.
- **Never commit runtime state or secrets.** `config.yaml`, `json/points.json`,
  `json/queues.json`, `json/fb_watch.json`, `api_key/*`, `private/`, `logs/`
  and `cogs_local/` are all gitignored for a reason — they contain real server
  IDs, tokens and data about real users. Run `git status` before committing and
  check nothing from that list snuck in.
- **Don't hardcode IDs.** Channel IDs, role IDs, guild IDs and hostnames belong
  in `config.yaml`, with a placeholder added to `config.example.yaml`. If a
  feature only makes sense on one server, gate it on a config value rather than
  a constant in the source.
- **Keep it one topic per PR.** Small and focused gets reviewed faster.

## Conventions

- Cogs live in `cogs/` and are auto-loaded by filename; a file needs an
  `async def setup(bot)` at the bottom. Server-specific or private cogs go in
  the gitignored `cogs_local/` instead — see the README.
- Read and write JSON through `storage.read_json` / `storage.write_json_atomic`,
  and take `storage.lock_for(path)` around read-modify-write sequences. The bot
  and the dashboard share a process, so unlocked writes really do race.
- Match the surrounding style: comments explain *why*, existing Chinese
  docstrings stay Chinese, no reformatting of untouched code.
- User-facing strings that name a feature should come from config where a
  precedent already exists (see `cogs/points.py`).

## Reporting a bug

Include what you ran, what happened, and what you expected. Logs help — but
scrub user IDs, tokens and server names before pasting them.
