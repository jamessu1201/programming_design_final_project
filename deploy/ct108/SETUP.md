# CT108 host-side autodeploy — one-time setup

Why: the in-process `!autodeploy` command can't work on CT108 (the container's
`/app` has no `.git`; we deploy via image rebuild). This sets up a **host-side**
poll: a systemd timer on CT108 that pulls `origin/main` every ~3 min and rebuilds
the image + restarts the container only when there are new commits.

All commands run **inside CT108** (`pct exec 108 -- bash` from PVE, or SSH into it).
Paths: repo `/root/dcbot`, data bind `/mnt/docker-data/dcbot`.

## 1. Read-only deploy key for the private repo

```bash
ssh-keygen -t ed25519 -f /root/.ssh/dcbot_deploy -N "" -C "ct108-dcbot-deploy"
cat /root/.ssh/dcbot_deploy.pub
```
Add that public key on GitHub: repo **Settings → Deploy keys → Add deploy key**
(leave "Allow write access" UNCHECKED). The autodeploy script already points git
at this key via `GIT_SSH_COMMAND`, so no `~/.ssh/config` needed.

## 2. Turn `/root/dcbot` into a git clone (in place, keeps `.env`)

`.env` is untracked (gitignored) so `git reset --hard` won't touch it; runtime
data (`json/`, `api_key/`, …) lives on the separate bind, not here.

```bash
cd /root/dcbot
git init -q
git remote add origin git@github.com:jamessu1201/programming_design_final_project.git
GIT_SSH_COMMAND="ssh -i /root/.ssh/dcbot_deploy -o StrictHostKeyChecking=accept-new" git fetch -q origin main
git reset --hard origin/main
git branch -M main
git branch --set-upstream-to=origin/main main
```
Sanity: `git status` clean, `ls deploy/ct108/` shows the script + units, and
`.env` still present (`ls -a | grep .env`).

## 3. Install + enable the timer

```bash
cp /root/dcbot/deploy/ct108/dcbot-autodeploy.service /etc/systemd/system/
cp /root/dcbot/deploy/ct108/dcbot-autodeploy.timer   /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now dcbot-autodeploy.timer
```

## 4. Verify

```bash
systemctl list-timers dcbot-autodeploy.timer      # shows next run
systemctl start dcbot-autodeploy.service          # run once now
tail -n 30 /var/log/dcbot-autodeploy.log          # "no change" or a build log
```

## Notes / behaviour

- **No change → does nothing** (cheap fetch). New commit → ff-merge, sync
  `config.yaml` to the bind *only if it changed in that pull*, `docker compose
  build`, `docker compose up -d`.
- **Build fails → running container is left as-is** (fail-safe); HEAD has already
  advanced, so it won't rebuild the same bad commit every cycle — push a fix and
  the next cycle deploys it.
- The script lives in the repo, so improving it = just push; the next pull updates it.
- Manual deploy is now also a one-liner:
  `cd /root/dcbot && git pull && docker compose build && docker compose up -d`.
- To pause autodeploy: `systemctl disable --now dcbot-autodeploy.timer`.
- Adjust cadence in the `.timer` (`OnUnitActiveSec`); reinstall + `daemon-reload`.
