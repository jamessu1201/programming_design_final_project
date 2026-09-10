[繁體中文](README.md) | **English**

# dcbot

A multi-functional Discord bot: music playback, an LLM assistant, a named-queue
system, activity points, LeetCode reminders, keyword-triggered meme responses,
and a FastAPI web dashboard — all in one process, with hot-reload and git
auto-deploy.

## Features

| Cog | Commands | Description |
|-----|----------|-------------|
| **Music** | `!play`, `!playnext`, `!skip`, `!queue`, `!loop`, `!pause`, `!resume`, `!stop`, `!leave` | YouTube music playback via yt-dlp + FFmpeg. `!playnext` (aliases `!pn` / `!insert`) jumps the song to the front of the queue |
| **API** | `!meme`, `!mygo`, `!weather`, `!elden`, `!picture`, `!hololive` | External API integrations (memes, weather, Elden Ring wiki, Unsplash, Holodex) |
| **Auto** | (automatic) | Daily LeetCode challenge, birthday greetings, LOL reminder, LeetCode contest reminders |
| **Event** | (automatic) | Keyword-triggered meme responses, bad word filter |
| **Others** | `!poll`, `!draw`, `!banwords`, `!prefix`, `!count` | Polls, lottery, banned-word management, custom prefix |
| **Queue** | `/queue add`, `/queue list`, `/queue top`, `/queue take`, `/queue pop`, `/queue queues`, `/queue clear`, `/queue setup`, `/queue setnext`, `/queue autooff` | Multiple named queues (slash commands + autocomplete): anyone can join, anyone can remove the head, but only your own entry elsewhere in the line. Optional cooldown auto-pops the head and tags the inviter to start a vote |
| **LLM** | `/ask`, `/forget`, `/botchat`, `/stopchat` | Talks to any OpenAI-compatible endpoint. `/ask` is one question / one answer (images supported for vision models); @-mention the bot for chat with short-term context; `/botchat` lets two bots talk to each other in a designated channel (throttled, with a turn cap) and `/stopchat` ends it. Supports function calling: time/arithmetic, weather, DuckDuckGo search, and looking up points and queues |
| **Points** | `/points top`, `/points view`, `/points active`, `/points reset`, `/points recompute` | Activity points: +1 per N minutes in voice, +1 per message. `/points active` lists everyone who hit a threshold over a rolling window (default "≥ 200 in the last 30 days"). Name, rates and which servers it applies to are all set in `config.yaml` |
| **FB watch** | `/fbwatch` | Subscribe to keywords and get a DM when a forwarded post matches (optional ntfy push to your phone) |
| **Conversation** | `!sendtext`, `!sendreply`, `!sendprivate` | Remote messaging (owner only) |
| **Admin** | `!reload`, `!ra`, `!deploy`, `!autodeploy`, `!bye` | Hot-reload, git auto-deploy, shutdown |
| **Dashboard** | (web UI at `/`) | FastAPI admin panel: banned words, auto-replies, prefix, autodeploy, ops buttons (OAuth login) |

## Setup

### 1. Clone

```bash
git clone https://github.com/jamessu1201/dcbot.git
cd dcbot
```

### 2. Python environment

```bash
python -m venv venv

# Linux / Mac
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -r requirements.txt
```

### 3. System dependencies

**FFmpeg** (required for music playback):

```bash
# Ubuntu / Debian
sudo apt install ffmpeg

# Mac
brew install ffmpeg

# Windows: download from https://ffmpeg.org/download.html
# Place ffmpeg.exe in the project root, or add it to PATH
```

**yt-dlp** is installed via `requirements.txt`. The bot auto-detects it from the venv.

### 4. Secret files

**The bot token is the only one that's actually required.** Everything else is
optional — without it, only the command that needs it replies "not configured".
The rest of the bot runs normally and no cog fails to load.

None of these are in git; create the ones you need yourself:

```bash
mkdir -p api_key private
```

| File (or env var) | Content | What happens without it |
|------|---------|------|
| `api_key/token.txt` (`bot_token`) | Discord bot token | **Won't start** — the only hard requirement |
| `private/owners.txt` | Comma-separated owner user IDs (e.g. `123456,789012`) | Falls back to your Discord application's owner, so you usually don't need this file |
| `api_key/cwa.txt` (`cwa_api_key`) | Taiwan CWA open-data key ([free signup](https://opendata.cwa.gov.tw/)) | `!weather` and the LLM weather tool report it's unconfigured |
| `api_key/access_key.txt` (`picture_access_key`) | Unsplash API access key | `!picture` replies `no picture_access_key` |
| `api_key/api.txt` (`holodex_api_key`) | Holodex API key | `!hololive` replies `no holodex_api_key` |
| `api_key/llm.txt` (`llm_api_key`) | OpenAI-compatible LLM API key | `/ask` and @-mention chat report they're unconfigured |
| `api_key/ntfy.txt` (`ntfy_token`) | ntfy auth token | Only needed if your ntfy server has auth enabled |
| `api_key/oauth.json` | Discord OAuth config for the web dashboard (see below) | The dashboard doesn't start; the bot itself is unaffected |

You don't need to create `api_key/session.key` — the dashboard generates it on
first start.

### 5. Configuration

```bash
cp config.example.yaml config.yaml
```

Then edit `config.yaml` with your own server's channel and role IDs. Every ID
defaults to `0` (disabled). To read an ID, turn on Discord's Developer Mode
(Settings → Advanced → Developer Mode), then right-click a channel or role →
Copy ID.

`config.yaml` is gitignored — your real IDs, endpoints and ntfy topics never end
up in a commit.

The activity points system is configured in the same file:

```yaml
points:
  guild_id: null            # null = every server; a guild ID = only that server
  display_name: 活躍點數     # call the leaderboard whatever you like
  emoji: "⭐"
  voice_minutes_per_point: 3   # one point per N minutes in voice
  message_points: 1
  active_days: 30         # default look-back for /points active (max 100)
  active_threshold: 200   # default threshold for /points active
  exclude_guests: true    # auto-exclude Discord guests (official IS_GUEST flag)
  excluded_roles: []      # extra role IDs that earn no points
```

After changing `display_name`, run `!reload points`; the slash command
descriptions additionally need a `!sync`.

`/points active` reads per-user daily buckets, which only start accumulating
once this feature is deployed. To fill in the past, run
`!points_backfill <days>` (bot owner only; add `dry` to preview) — it scans
message history. **Messages only: Discord keeps no history of voice presence
and exposes no API for it, so past voice minutes cannot be recovered.** Days
that already have data are never overwritten, so re-running is safe.

### 6. Run

```bash
python project.py
```

## Private / local cogs

`cogs_local/` is an optional, gitignored second cog directory. Anything you drop
in there is loaded exactly like a cog in `cogs/`, so you can keep
server-specific or privacy-sensitive cogs out of the repo entirely:

```
cogs_local/
  my_private_cog.py
```

`!reload my_private_cog` finds it there too. If the directory doesn't exist it's
silently skipped, so a plain clone works out of the box. Auto-deploy never
touches it, because it isn't in git.

## Auto-deploy

The bot supports hot-reload without restarting:

| Command | Description |
|---------|-------------|
| `!reload <cog>` | Reload a single cog + its external dependencies |
| `!ra` | Reload all cogs at once |
| `!deploy` | Manual git pull + reload changed files |
| `!autodeploy` | Toggle auto-deploy: polls git every 30s, auto pulls & reloads |

Workflow: push changes to GitHub and the running bot pulls and reloads itself.
If any cog fails to reload after a pull, the working tree is reset to the
pre-pull commit and the affected cogs are reloaded from the old code.

## Project structure

```
project.py              # Entry point
config.example.yaml     # Config template -> copy to config.yaml
leetcode.py             # LeetCode API (daily challenge + contests)
notify.py               # ntfy push helper
storage.py              # Atomic JSON read/write + per-file locks
requirements.txt        # Python dependencies
cogs/
  admin.py              # Bot management, hot-reload, auto-deploy
  api.py                # External API commands
  auto.py               # Scheduled tasks (daily, contests, reminders)
  conversation.py       # Remote messaging
  event.py              # Message listeners, meme responses, word filter
  fbwatch.py            # Keyword subscriptions -> DM / ntfy
  llm.py                # LLM assistant (OpenAI-compatible endpoint)
  music.py              # YouTube music player
  others.py             # Polls, lottery, prefix, misc
  points.py             # Activity points (voice + messages)
  queue.py              # Multiple named queues (slash commands + autocomplete)
  role_select.py        # Self-service role buttons
  scheduled.py          # Cron-style scheduled messages
cogs_local/             # Optional private cogs (gitignored)
dashboard/              # FastAPI admin UI
json/
  auto_replies.json     # Meme trigger words + image URLs (editable)
  badword.json          # Per-server banned words
  prefix.json           # Per-server command prefixes
  pic_database.json     # Meme index for !mygo (3163 entries)
  time.json             # Music playback state
  queues.json           # Queue data (created at runtime, gitignored)
  points.json           # Points data (created at runtime, gitignored)
  fb_watch.json         # Keyword subscriptions (created at runtime, gitignored)
```

## Privacy / data handling

Self-hosting this bot means storing data about real people in your server. Know
what it writes before you deploy it:

| File | Contains |
|------|----------|
| `json/points.json` | user IDs, display names, message and voice-minute counts |
| `json/fb_watch.json` | user IDs mapped to the keywords they subscribed to |
| `json/queues.json` | user IDs in each queue |
| `dashboard/audit.jsonl` | who changed what through the dashboard |
| `logs/` | only if you add a message-logging cog of your own |

All of these are gitignored. A few things worth doing anyway:

- Tell your members what the bot records — some of it is not obvious to them.
- ntfy topics act as passwords: anyone who guesses one can read those pushes.
  Use long random topic names, keep them in `config.yaml`, and never commit them.
- Follow the [Discord Developer Terms of Service][ddtos] and the platform's
  rules on storing user data.

[ddtos]: https://discord.com/developers/docs/policies-and-agreements/developer-terms-of-service

## Docker

```bash
cp .env.example .env      # set bot_token, DCBOT_DATA, DASHBOARD_HOST
docker compose up -d --build
```

`DCBOT_DATA` points at the directory holding `config.yaml`, `json/`, `api_key/`,
`private/`, `logs/` and the optional `cogs_local/`. Those are bind-mounted into
the container, so the image stays stateless and rebuilds never touch your data.

The compose file assumes an existing external Traefik network. If you don't use
Traefik, drop the two `networks:` keys and the `labels:` block, and add
`ports: ["8080:8080"]` instead.

## Web dashboard

The FastAPI dashboard runs in the same process as the bot. From a browser you
can edit banned words, auto-replies and the prefix, toggle autodeploy, and press
buttons to sync slash commands / reload all cogs / git pull. Authorization goes
through Discord OAuth2: only bot owners and people with the *Manage Server*
permission can get in.

### 1. Create Discord OAuth credentials

1. Open your bot's application in the [Discord Developer Portal](https://discord.com/developers/applications)
2. Left sidebar → **OAuth2 → General**:
   - Copy the `Client ID` and `Client Secret`
   - Under **Redirects**, add:
     - for development: `http://localhost:8080/auth/callback`
     - for production: `https://dashboard.example.com/auth/callback` (your own domain)
3. Copy the template and fill it in:
   ```bash
   cp api_key/oauth.json.example api_key/oauth.json
   ```
   ```json
   {
     "client_id": "...",
     "client_secret": "...",
     "redirect_uri": "https://dashboard.example.com/auth/callback",
     "host": "127.0.0.1",
     "port": 8080
   }
   ```

`api_key/oauth.json`, `api_key/session.key` and `dashboard/audit.jsonl` are all
gitignored and never reach the repo.

### 2. Start it

Once `pip install -r requirements.txt` is done, the dashboard cog brings up
uvicorn automatically when the bot starts. Test it locally at
`http://localhost:8080`.

### 3. Expose it with a Cloudflare Tunnel (optional)

```bash
cloudflared tunnel create bot-dashboard
cloudflared tunnel route dns bot-dashboard dashboard.example.com
```

`~/.cloudflared/config.yml`:
```yaml
tunnel: <tunnel-uuid>
credentials-file: /home/<user>/.cloudflared/<tunnel-uuid>.json
ingress:
  - hostname: dashboard.example.com
    service: http://localhost:8080
  - service: http_status:404
```

```bash
cloudflared tunnel run bot-dashboard         # or run it as a systemd service
```

Cloudflare handles TLS, caching and DDoS protection; the bot machine only
listens on `127.0.0.1` and doesn't need an open port. For another layer, use
Cloudflare Zero Trust → Access to allow only specific email addresses.

### 4. Permissions

| Role | Can see | Can change |
|------|---------|------------|
| Bot owner (`private/owners.txt`) | every server + the ops panel | everything |
| *Manage Server* permission in a guild | that guild's banned words / auto-reply toggle / prefix | that guild only |
| Everyone else | (403) | — |

Every write appends a line to `dashboard/audit.jsonl` so changes can be traced
afterwards.

## Adding meme responses

Edit `json/auto_replies.json`:

```json
[
  {
    "triggers": ["keyword1", "keyword2"],
    "urls": ["https://example.com/image.jpg"]
  }
]
```

Then run `!reload_replies` in Discord (no restart needed).

## Contributing

PRs welcome — see [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
