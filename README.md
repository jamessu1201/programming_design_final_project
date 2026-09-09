# dcbot

A multi-functional Discord bot: music playback, an LLM assistant, a named-queue
system, activity points, LeetCode reminders, meme auto-responses, and a FastAPI
web dashboard — all in one process, with hot-reload and git auto-deploy.

## Features

| Cog | Commands | Description |
|-----|----------|-------------|
| **Music** | `!play`, `!skip`, `!queue`, `!loop`, `!pause`, `!resume`, `!stop`, `!leave` | YouTube music playback via yt-dlp + FFmpeg |
| **API** | `!meme`, `!mygo`, `!weather`, `!elden`, `!picture`, `!hololive` | External API integrations (memes, weather, Elden Ring wiki, Unsplash, Holodex) |
| **Auto** | (automatic) | Daily LeetCode challenge, birthday greetings, LOL reminder, LeetCode contest reminders |
| **Event** | (automatic) | Keyword-triggered meme responses, bad word filter |
| **Others** | `!poll`, `!draw`, `!banwords`, `!prefix`, `!count` | Voting, lottery, word filter management, custom prefix |
| **Queue** | `/queue add`, `/queue list`, `/queue top`, `/queue take`, `/queue pop`, `/queue queues`, `/queue clear`, `/queue setup`, `/queue setnext`, `/queue autooff` | 多具名排隊系統（slash + autocomplete）：人人可加、隊頭人人可移除、中間/尾端只能拿自己的；可開冷卻期，到期自動 pop 並 tag 邀請人開投票 |
| **LLM** | `/ask`, `/forget`, `/botchat`, `/stopchat` | 接 OpenAI 相容端點：`/ask` 一問一答（可附圖看圖）、@機器人 聊天（短期上下文）、`/botchat` 讓兩隻機器人在指定頻道互聊（節流＋上限），`/stopchat` 喊停。支援 function calling 工具：時間/計算、天氣、DuckDuckGo 搜尋、查點數與 queue |
| **Points** | `/points top`, `/points view`, `/points reset`, `/points recompute` | 活躍度點數：語音每分鐘 +1、訊息每則 +1，看排行榜與個人點數。名稱、費率、適用伺服器都在 `config.yaml` 設定 |
| **FB watch** | `/fbwatch` | 訂閱關鍵字，命中轉貼文章時 DM（可選 ntfy 手機推播） |
| **Conversation** | `!sendtext`, `!sendreply`, `!sendprivate` | Remote messaging (owner only) |
| **Admin** | `!reload`, `!ra`, `!deploy`, `!autodeploy`, `!bye` | Hot-reload, git auto-deploy, shutdown |
| **Dashboard** | (web UI at `/`) | FastAPI 管理面板：ban 詞、自動回應、prefix、autodeploy、維運按鈕（OAuth 登入） |

## Setup

### 1. Clone

```bash
git clone https://github.com/<your-account>/dcbot.git
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

These files are **not** in git. You must create them manually:

```bash
mkdir -p api_key private
```

| File | Content | Required |
|------|---------|----------|
| `api_key/token.txt` | Discord bot token (or env `bot_token`) | Yes |
| `private/owners.txt` | Comma-separated owner user IDs (e.g. `123456,789012`) | Yes |
| `api_key/access_key.txt` | Unsplash API access key | For `!picture` |
| `api_key/api.txt` | Holodex API key | For `!hololive` |
| `api_key/llm.txt` | OpenAI-compatible LLM API key (or env `llm_api_key`) | For `/ask` & @mention chat |
| `api_key/ntfy.txt` | ntfy auth token (or env `ntfy_token`) | Only if your ntfy server requires auth |

### 5. Configuration

```bash
cp config.example.yaml config.yaml
```

Then edit `config.yaml` with your server's channel and role IDs. Every ID is
`0` (disabled) by default; to read an ID, turn on Discord's 開發者模式 and
right-click a channel or role → 複製 ID.

`config.yaml` is gitignored — your real IDs, endpoints and ntfy topics never
end up in a commit.

The activity points system is configured there too:

```yaml
points:
  guild_id: null          # null = every server; a guild ID = only that server
  display_name: 活躍點數   # whatever you want the leaderboard to call itself
  emoji: "⭐"
  voice_points_per_min: 1
  message_points: 1
```

After changing `display_name`, run `!reload points`; the slash command
descriptions additionally need a `!sync`.

### 6. Run

```bash
python project.py
```

## Private / local cogs

`cogs_local/` is an optional, gitignored second cog directory. Anything you drop
in there is loaded exactly like a cog in `cogs/`, so you can keep server-specific
or privacy-sensitive cogs out of the repo entirely:

```
cogs_local/
  my_private_cog.py
```

`!reload my_private_cog` finds it there too. If the directory doesn't exist it's
silently skipped, so a plain clone works out of the box. Auto-deploy never
touches it, because it isn't in git.

## Auto-deploy

The bot supports hot-reload without restart:

| Command | Description |
|---------|-------------|
| `!reload <cog>` | Reload a single cog + its external dependencies |
| `!ra` | Reload all cogs at once |
| `!deploy` | Manual git pull + reload changed files |
| `!autodeploy` | Toggle auto-deploy: polls git every 30s, auto pulls & reloads |

Workflow: push changes to GitHub, and the running bot will auto-pull and reload.
If any cog fails to reload after a pull, the working tree is reset to the
pre-pull commit and the affected cogs are reloaded from the old code.

## Project Structure

```
project.py              # Entry point
config.example.yaml     # Config template -> copy to config.yaml
leetcode.py             # LeetCode API (daily + contests)
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
  queue.py              # 多具名排隊系統（slash 指令 + autocomplete）
  role_select.py        # Self-service role buttons
  scheduled.py          # Cron-style scheduled messages
cogs_local/             # Optional private cogs (gitignored)
dashboard/              # FastAPI admin UI
json/
  auto_replies.json     # Meme trigger words + image URLs (editable)
  badword.json          # Per-server banned words
  prefix.json           # Per-server command prefixes
  time.json             # Music playback state
  queues.json           # 排隊資料（執行期自動產生，已 gitignore）
  points.json           # 點數資料（執行期自動產生，已 gitignore）
  fb_watch.json         # 關鍵字訂閱（執行期自動產生，已 gitignore）
```

## Privacy / data handling

Self-hosting this bot means storing data about the people in your server. Know
what gets written before you deploy it:

| File | Contains |
|------|----------|
| `json/points.json` | user IDs, display names, message/voice-minute counts |
| `json/fb_watch.json` | user IDs mapped to the keywords they subscribed to |
| `json/queues.json` | user IDs in each queue |
| `dashboard/audit.jsonl` | who changed what through the dashboard |
| `logs/` | only if you add a message-logging cog of your own |

All of these are gitignored. A few things worth doing anyway:

- Tell your members what the bot records — some of it is not obvious to them.
- ntfy topics act as passwords: anyone who guesses one can read those pushes.
  Use long random topic names and keep them in `config.yaml`, never in a commit.
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
Traefik, drop the `networks:` keys and the `labels:` block and add
`ports: ["8080:8080"]` instead.

## Web dashboard

A FastAPI 後台跟 bot 同 process 跑，可以從瀏覽器調 ban 詞、autoreply、prefix、autodeploy，
也能按按鈕 sync slash / reload all / git pull。授權走 Discord OAuth2，只有 bot owner 與
有 `管理伺服器` 權限的人能進來。

### 1. 建立 Discord OAuth credentials

1. 在 [Discord Developer Portal](https://discord.com/developers/applications) 進入你 bot 的 Application
2. 左側 **OAuth2 → General**：
   - 抄 `Client ID` 與 `Client Secret`
   - 在 **Redirects** 加：
     - 開發 `http://localhost:8080/auth/callback`
     - 線上 `https://dashboard.example.com/auth/callback`（換成你的網域）
3. 複製範本並填入：
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

`api_key/oauth.json`、`api_key/session.key`、`dashboard/audit.jsonl` 都已被 `.gitignore`，
不會進 repo。

### 2. 啟動

裝完 `pip install -r requirements.txt` 之後 dashboard cog 會在 bot 啟動時自動掛上 uvicorn。
本機用 `http://localhost:8080` 直接測。

### 3. 用 Cloudflare Tunnel 公開（可選）

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
cloudflared tunnel run bot-dashboard         # 或做成 systemd service
```

Cloudflare 自動 TLS、cache、DDoS 防護；bot 機本身只 listen `127.0.0.1`，不需要開 port。
要再加一層保護可以在 Cloudflare Zero Trust → Access 設只允許特定 email。

### 4. 權限規則

| 角色 | 看得到 | 能改 |
|------|--------|------|
| Bot owner（`private/owners.txt`） | 所有伺服器 + 維運面板 | 全部 |
| 在某 guild 有 `管理伺服器` 權限 | 該 guild 的 ban 詞 / autoreply 開關 / prefix | 限該 guild |
| 其他人 | （403） | — |

每筆寫操作都會 append 一行進 `dashboard/audit.jsonl`，方便事後追責。

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
