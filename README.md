# Discord Bot - James and Michael's Bot

A multi-functional Discord bot with music playback, auto-attendance, LeetCode daily challenges, meme responses, and more.

## Features

| Cog | Commands | Description |
|-----|----------|-------------|
| **Music** | `!play`, `!skip`, `!queue`, `!loop`, `!pause`, `!resume`, `!stop`, `!leave` | YouTube music playback via yt-dlp + FFmpeg |
| **API** | `!meme`, `!mygo`, `!weather`, `!elden`, `!picture`, `!hololive` | External API integrations (memes, weather, Elden Ring wiki, Unsplash, Holodex) |
| **Auto** | (automatic) | Daily LeetCode challenge, birthday greetings, LOL reminder, LeetCode contest reminders |
| **Attend** | `!attend` | Auto-attendance for CCU ecourse2 (Playwright + 2Captcha) |
| **Event** | (automatic) | Keyword-triggered meme responses, bad word filter |
| **Others** | `!poll`, `!draw`, `!banwords`, `!prefix`, `!count` | Voting, lottery, word filter management, custom prefix |
| **Conversation** | `!sendtext`, `!sendreply`, `!sendprivate` | Remote messaging (owner only) |
| **Admin** | `!reload`, `!ra`, `!deploy`, `!autodeploy`, `!bye` | Hot-reload, git auto-deploy, shutdown |
| **Dashboard** | (web UI at `/`) | FastAPI 管理面板：ban 詞、自動回應、prefix、autodeploy、維運按鈕（OAuth 登入） |

## Setup

### 1. Clone

```bash
git clone https://github.com/jamessu1201/programming_design_final_project.git
cd programming_design_final_project
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
mkdir -p api_key private/json
```

| File | Content | Required |
|------|---------|----------|
| `api_key/token.txt` | Discord bot token | Yes |
| `private/owners.txt` | Comma-separated owner user IDs (e.g. `123456,789012`) | Yes |
| `api_key/access_key.txt` | Unsplash API access key | For `!picture` |
| `api_key/api.txt` | Holodex API key | For `!hololive` |
| `private/two_captcha.txt` | 2Captcha API key | For `!attend` |
| `private/json/account.json` | `{"accounts":["user"],"passwords":["pass"]}` | For `!attend` |

### 5. Configuration

Edit `config.yaml` to set your server's channel and role IDs:

```yaml
channels:
  birthday: 1234567890      # Birthday greeting channel
  leetcode: 1234567890      # LeetCode daily / contest channel
  lol: 1234567890            # LOL reminder channel
  reaction_delete: 1234567890 # Auto-delete on reaction channel

roles:
  birthday:
    - 1234567890             # Birthday role IDs
  birthday_ping: 1234567890
  lol: 1234567890
  leetcode_contest: 1234567890
```

### 6. Run

```bash
python project.py
```

## Auto-deploy

The bot supports hot-reload without restart:

| Command | Description |
|---------|-------------|
| `!reload <cog>` | Reload a single cog + its external dependencies |
| `!ra` | Reload all cogs at once |
| `!deploy` | Manual git pull + reload changed files |
| `!autodeploy` | Toggle auto-deploy: polls git every 30s, auto pulls & reloads |

Workflow: push changes to GitHub, and the running bot will auto-pull and reload.

## Project Structure

```
project.py              # Entry point
config.yaml             # Channel / role IDs
leetcode.py             # LeetCode API (daily + contests)
attend_playwright.py    # Attendance automation (async, Playwright)
attend_program.py       # Attendance automation (sync, Selenium)
requirements.txt        # Python dependencies
cogs/
  admin.py              # Bot management, hot-reload, auto-deploy
  api.py                # External API commands
  attend.py             # Attendance commands
  auto.py               # Scheduled tasks (daily, contests, reminders)
  conversation.py       # Remote messaging
  event.py              # Message listeners, meme responses, word filter
  music.py              # YouTube music player
  others.py             # Polls, lottery, prefix, misc
json/
  auto_replies.json     # Meme trigger words + image URLs (editable)
  badword.json          # Per-server banned words
  prefix.json           # Per-server command prefixes
  time.json             # Music playback state
```

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
     - 線上 `https://dashboard.jamessu1201.com/auth/callback`（換成你的網域）
3. 複製範本並填入：
   ```bash
   cp api_key/oauth.json.example api_key/oauth.json
   ```
   ```json
   {
     "client_id": "...",
     "client_secret": "...",
     "redirect_uri": "https://dashboard.jamessu1201.com/auth/callback",
     "host": "127.0.0.1",
     "port": 8080
   }
   ```

`api_key/oauth.json`、`api_key/session.key`、`dashboard/audit.jsonl` 都已被 `.gitignore`，
不會進 repo。

### 2. 啟動

裝完 `pip install -r requirements.txt` 之後 dashboard cog 會在 bot 啟動時自動掛上 uvicorn。
本機用 `http://localhost:8080` 直接測。

### 3. 用 Cloudflare Tunnel 公開（推薦）

```bash
cloudflared tunnel create bot-dashboard
cloudflared tunnel route dns bot-dashboard dashboard.jamessu1201.com
```

`~/.cloudflared/config.yml`:
```yaml
tunnel: <tunnel-uuid>
credentials-file: /home/jamessu/.cloudflared/<tunnel-uuid>.json
ingress:
  - hostname: dashboard.jamessu1201.com
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
