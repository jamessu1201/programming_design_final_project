**繁體中文** | [English](README.en.md)

# dcbot

一隻多功能 Discord 機器人：音樂播放、LLM 助手、具名排隊系統、活躍度點數、LeetCode 提醒、
關鍵字迷因回應，外加一個 FastAPI 網頁管理後台——全部跑在同一個 process 裡，支援熱重載與
git 自動部署。

## 功能

| Cog | 指令 | 說明 |
|-----|------|------|
| **Music** | `!play`、`!skip`、`!queue`、`!loop`、`!pause`、`!resume`、`!stop`、`!leave` | 用 yt-dlp + FFmpeg 播 YouTube 音樂 |
| **API** | `!meme`、`!mygo`、`!weather`、`!elden`、`!picture`、`!hololive` | 串接外部 API（迷因、天氣、Elden Ring wiki、Unsplash、Holodex） |
| **Auto** | （自動） | 每日 LeetCode 題目、生日祝賀、LOL 提醒、LeetCode 周賽提醒 |
| **Event** | （自動） | 關鍵字觸發迷因回應、髒話過濾 |
| **Others** | `!poll`、`!draw`、`!banwords`、`!prefix`、`!count` | 投票、抽獎、禁字管理、自訂前綴 |
| **Queue** | `/queue add`、`/queue list`、`/queue top`、`/queue take`、`/queue pop`、`/queue queues`、`/queue clear`、`/queue setup`、`/queue setnext`、`/queue autooff` | 多具名排隊系統（slash + autocomplete）：人人可加、隊頭人人可移除、中間/尾端只能拿自己的；可開冷卻期，到期自動 pop 並 tag 邀請人開投票 |
| **LLM** | `/ask`、`/forget`、`/botchat`、`/stopchat` | 接 OpenAI 相容端點：`/ask` 一問一答（可附圖看圖）、@機器人 聊天（短期上下文）、`/botchat` 讓兩隻機器人在指定頻道互聊（節流＋上限），`/stopchat` 喊停。支援 function calling 工具：時間/計算、天氣、DuckDuckGo 搜尋、查點數與 queue |
| **Points** | `/points top`、`/points view`、`/points reset`、`/points recompute` | 活躍度點數：語音每分鐘 +1、訊息每則 +1，看排行榜與個人點數。名稱、費率、適用伺服器都在 `config.yaml` 設定 |
| **FB watch** | `/fbwatch` | 訂閱關鍵字，命中轉貼文章時 DM 通知（可選 ntfy 手機推播） |
| **Conversation** | `!sendtext`、`!sendreply`、`!sendprivate` | 遠端代發訊息（限 owner） |
| **Admin** | `!reload`、`!ra`、`!deploy`、`!autodeploy`、`!bye` | 熱重載、git 自動部署、關機 |
| **Dashboard** | （網頁後台 `/`） | FastAPI 管理面板：禁字、自動回應、prefix、autodeploy、維運按鈕（OAuth 登入） |

## 安裝

### 1. 取得程式碼

```bash
git clone https://github.com/jamessu1201/dcbot.git
cd dcbot
```

### 2. Python 環境

```bash
python -m venv venv

# Linux / Mac
source venv/bin/activate

# Windows
venv\Scripts\activate

pip install -r requirements.txt
```

### 3. 系統相依套件

**FFmpeg**（音樂播放必需）：

```bash
# Ubuntu / Debian
sudo apt install ffmpeg

# Mac
brew install ffmpeg

# Windows：到 https://ffmpeg.org/download.html 下載，
# 把 ffmpeg.exe 放進專案根目錄，或加進 PATH
```

**yt-dlp** 會由 `requirements.txt` 一起裝好，機器人會自動從 venv 裡找到它。

### 4. 金鑰檔案

這些檔案**不在 git 裡**，要自己建立：

```bash
mkdir -p api_key private
```

| 檔案 | 內容 | 必要性 |
|------|------|--------|
| `api_key/token.txt` | Discord bot token（或用環境變數 `bot_token`） | 必要 |
| `private/owners.txt` | 逗號分隔的 owner 使用者 ID（例：`123456,789012`） | 必要 |
| `api_key/access_key.txt` | Unsplash API access key | `!picture` 需要 |
| `api_key/api.txt` | Holodex API key | `!hololive` 需要 |
| `api_key/llm.txt` | OpenAI 相容端點的 API key（或用環境變數 `llm_api_key`） | `/ask` 與 @機器人 聊天需要 |
| `api_key/ntfy.txt` | ntfy 驗證 token（或用環境變數 `ntfy_token`） | 只有你的 ntfy server 需要驗證時才用 |

### 5. 設定檔

```bash
cp config.example.yaml config.yaml
```

然後編輯 `config.yaml`，填入你自己伺服器的頻道與身分組 ID。所有 ID 預設都是 `0`（＝停用）；
要查 ID 的話，先在 Discord 打開「設定 → 進階 → 開發者模式」，然後右鍵頻道或身分組 → 複製 ID。

`config.yaml` 已經被 gitignore——你的真實 ID、端點與 ntfy topic 不會跑進 commit 裡。

活躍度點數系統也在同一個檔案設定：

```yaml
points:
  guild_id: null          # null = 所有伺服器都啟用；填 guild ID = 只在該伺服器啟用
  display_name: 活躍點數   # 排行榜要叫什麼名字都可以
  emoji: "⭐"
  voice_points_per_min: 1
  message_points: 1
```

改完 `display_name` 之後跑 `!reload points`；slash 指令的描述還要再跑一次 `!sync` 才會更新。

### 6. 啟動

```bash
python project.py
```

## 私有 / 本地 cog

`cogs_local/` 是一個可選的、被 gitignore 掉的第二個 cog 目錄。丟進去的檔案會跟 `cogs/` 裡的
cog 一樣被載入，所以你可以把「只有自己伺服器要用」或「涉及隱私」的 cog 完全留在 repo 之外：

```
cogs_local/
  my_private_cog.py
```

`!reload my_private_cog` 也找得到它。目錄不存在就會靜默跳過，所以直接 clone 下來就能跑。
自動部署永遠不會動到這個目錄，因為它根本不在 git 裡。

## 自動部署

機器人支援不重啟的熱重載：

| 指令 | 說明 |
|------|------|
| `!reload <cog>` | 重載單一 cog 及其外部相依模組 |
| `!ra` | 一次重載所有 cog |
| `!deploy` | 手動 git pull + 重載變更的檔案 |
| `!autodeploy` | 切換自動部署：每 30 秒輪詢 git，自動 pull 並重載 |

用法：把改動 push 到 GitHub，執行中的機器人就會自己拉下來並重載。
如果 pull 之後有任何 cog 重載失敗，工作目錄會被重設回 pull 前的 commit，
受影響的 cog 也會用舊程式碼重載回去。

## 專案結構

```
project.py              # 進入點
config.example.yaml     # 設定範本 -> 複製成 config.yaml
leetcode.py             # LeetCode API（每日題目 + 競賽）
notify.py               # ntfy 推播 helper
storage.py              # 原子性 JSON 讀寫 + 每檔案鎖
requirements.txt        # Python 相依套件
cogs/
  admin.py              # 機器人管理、熱重載、自動部署
  api.py                # 外部 API 指令
  auto.py               # 排程任務（每日、競賽、提醒）
  conversation.py       # 遠端代發訊息
  event.py              # 訊息監聽、迷因回應、禁字過濾
  fbwatch.py            # 關鍵字訂閱 -> DM / ntfy
  llm.py                # LLM 助手（OpenAI 相容端點）
  music.py              # YouTube 音樂播放器
  others.py             # 投票、抽獎、prefix、雜項
  points.py             # 活躍度點數（語音 + 訊息）
  queue.py              # 多具名排隊系統（slash 指令 + autocomplete）
  role_select.py        # 自助選身分組按鈕
  scheduled.py          # cron 式排程訊息
cogs_local/             # 可選的私有 cog（已 gitignore）
dashboard/              # FastAPI 管理後台
json/
  auto_replies.json     # 迷因觸發詞 + 圖片網址（可編輯）
  badword.json          # 各伺服器的禁字
  prefix.json           # 各伺服器的指令前綴
  time.json             # 音樂播放狀態
  queues.json           # 排隊資料（執行期自動產生，已 gitignore）
  points.json           # 點數資料（執行期自動產生，已 gitignore）
  fb_watch.json         # 關鍵字訂閱（執行期自動產生，已 gitignore）
```

## 隱私 / 資料處理

自架這隻機器人，就等於在保存你伺服器裡真實成員的資料。部署之前先搞清楚它會寫下什麼：

| 檔案 | 內容 |
|------|------|
| `json/points.json` | 使用者 ID、顯示名稱、訊息數與語音分鐘數 |
| `json/fb_watch.json` | 使用者 ID 對應到他訂閱的關鍵字 |
| `json/queues.json` | 各個 queue 裡的使用者 ID |
| `dashboard/audit.jsonl` | 誰透過後台改了什麼 |
| `logs/` | 只有在你自己加了記錄訊息的 cog 時才會有東西 |

以上全部都已經 gitignore。不過還是有幾件事建議做：

- 告訴你的成員這隻機器人記錄了什麼——其中有些對他們來說並不明顯。
- ntfy 的 topic 等同密碼：猜到的人就能讀到那些推播。請用夠長夠亂的 topic 名稱，
  而且只寫在 `config.yaml` 裡，絕對不要進 commit。
- 遵守 [Discord 開發者服務條款][ddtos] 以及平台對於保存使用者資料的規範。

[ddtos]: https://discord.com/developers/docs/policies-and-agreements/developer-terms-of-service

## Docker

```bash
cp .env.example .env      # 設定 bot_token、DCBOT_DATA、DASHBOARD_HOST
docker compose up -d --build
```

`DCBOT_DATA` 指向存放 `config.yaml`、`json/`、`api_key/`、`private/`、`logs/` 與可選的
`cogs_local/` 的那個目錄。這些會以 bind mount 掛進容器，所以 image 保持無狀態，
重新 build 也不會動到你的資料。

compose 檔預設你已經有一個外部的 Traefik network。如果你不用 Traefik，
把 `networks:` 那兩處和 `labels:` 區塊刪掉，改加 `ports: ["8080:8080"]` 就好。

## 網頁後台

FastAPI 後台跟機器人同 process 跑，可以從瀏覽器調禁字、自動回應、prefix、autodeploy，
也能按按鈕 sync slash / reload all / git pull。授權走 Discord OAuth2，只有 bot owner 與
有「管理伺服器」權限的人能進來。

### 1. 建立 Discord OAuth credentials

1. 在 [Discord Developer Portal](https://discord.com/developers/applications) 進入你 bot 的 Application
2. 左側 **OAuth2 → General**：
   - 抄 `Client ID` 與 `Client Secret`
   - 在 **Redirects** 加：
     - 開發用 `http://localhost:8080/auth/callback`
     - 線上用 `https://dashboard.example.com/auth/callback`（換成你的網域）
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

裝完 `pip install -r requirements.txt` 之後，dashboard cog 會在機器人啟動時自動掛上 uvicorn。
本機用 `http://localhost:8080` 直接測。

### 3. 用 Cloudflare Tunnel 公開（可選）

```bash
cloudflared tunnel create bot-dashboard
cloudflared tunnel route dns bot-dashboard dashboard.example.com
```

`~/.cloudflared/config.yml`：
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

Cloudflare 會自動處理 TLS、cache、DDoS 防護；機器人本身只 listen `127.0.0.1`，不需要開 port。
要再加一層保護，可以在 Cloudflare Zero Trust → Access 設定只允許特定 email。

### 4. 權限規則

| 角色 | 看得到 | 能改 |
|------|--------|------|
| Bot owner（`private/owners.txt`） | 所有伺服器 + 維運面板 | 全部 |
| 在某 guild 有「管理伺服器」權限 | 該 guild 的禁字 / 自動回應開關 / prefix | 限該 guild |
| 其他人 | （403） | — |

每筆寫入操作都會 append 一行進 `dashboard/audit.jsonl`，方便事後追查。

## 新增迷因回應

編輯 `json/auto_replies.json`：

```json
[
  {
    "triggers": ["關鍵字1", "關鍵字2"],
    "urls": ["https://example.com/image.jpg"]
  }
]
```

然後在 Discord 跑 `!reload_replies`（不用重啟）。

## 參與貢獻

歡迎發 PR——請先看 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 授權

[MIT](LICENSE)
