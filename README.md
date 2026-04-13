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
