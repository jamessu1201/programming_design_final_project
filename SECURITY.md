# Security Policy

## Reporting a vulnerability

Please **don't** open a public issue for a security problem.

Use GitHub's private reporting instead: the **Security** tab → *Report a
vulnerability*. That opens a private advisory only the maintainers can see.

Useful things to include: what an attacker can do, the smallest reproduction you
have, and which files are involved. Scrub tokens, user IDs and server names from
anything you paste.

## Scope

This is a self-hosted bot, so most of the security surface belongs to whoever
runs it. Issues in this repo's code that are in scope:

- Anything letting a non-owner reach owner-only commands or dashboard routes.
- Auth flaws in the dashboard (OAuth handling, session cookies, CSRF).
- Code paths that leak the contents of `api_key/`, `private/` or `config.yaml`
  into Discord messages, logs or HTTP responses.
- Command handling that lets untrusted input run shell commands or read
  arbitrary files.

Out of scope: a deployment that has published its own tokens, guessable ntfy
topics chosen by the operator, and anything requiring the attacker to already be
a bot owner.

## If you run this bot

- Keep `api_key/`, `private/` and `config.yaml` off git — they're gitignored,
  but check `git status` before committing.
- Only put people you trust in `private/owners.txt`; owners can run `!deploy`
  and reset data.
- Don't expose the dashboard without a proxy in front of it. `api_key/oauth.json`
  defaults to `127.0.0.1` on purpose.
- Rotate the bot token immediately if it ever lands in a commit, a screenshot or
  a log. Discord will also invalidate tokens it detects publicly.
