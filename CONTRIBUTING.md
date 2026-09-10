# 參與貢獻 / Contributing

感謝你願意看一眼。issue 跟 PR 都歡迎，中英文皆可。
*(English below.)*

## 環境準備

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp config.example.yaml config.yaml
```

你需要自己的 Discord bot token，放在 `api_key/token.txt`（或環境變數 `bot_token`），
以及自己的使用者 ID，放在 `private/owners.txt`。請拿一個測試用伺服器來試，不要用正式的——
好幾個功能都會依伺服器寫入狀態。

```bash
python project.py
```

## 發 PR 之前

- **`python -m compileall -q -x '(^|/)venv/' .` 要過，`ruff check .` 也要過。**
  CI 跑的就是這兩個。機器人會在 push 到 `main` 之後約 30 秒內熱重載變更的 cog，
  所以語法錯誤幾乎是立刻上線。
- **絕對不要提交執行期狀態或機密。** `config.yaml`、`json/points.json`、`json/queues.json`、
  `json/fb_watch.json`、`api_key/*`、`private/`、`logs/`、`cogs_local/` 全部都有被 gitignore
  是有原因的——它們裝的是真實的伺服器 ID、token，以及真實使用者的資料。
  commit 前先跑 `git status`，確認上面這些沒有混進去。
- **不要硬編 ID。** 頻道 ID、身分組 ID、guild ID、主機名稱都該放進 `config.yaml`，
  同時在 `config.example.yaml` 加上對應的佔位值。如果某個功能只對一個伺服器有意義，
  請用設定值來控制，而不是在原始碼裡寫死一個常數。
- **一個 PR 一個主題。** 小而專注的改動會被更快 review。

## 慣例

- Cog 放在 `cogs/`，會依檔名自動載入；檔案底部要有 `async def setup(bot)`。
  只給特定伺服器用或涉及隱私的 cog，請改放進被 gitignore 的 `cogs_local/`（見 README）。
- 讀寫 JSON 一律透過 `storage.read_json` / `storage.write_json_atomic`，
  read-modify-write 的區段要用 `storage.lock_for(path)` 包起來。
  機器人和後台共用同一個 process，沒上鎖的寫入是真的會互相衝突的。
- 配合週遭既有風格：註解解釋「為什麼」，既有的中文 docstring 就維持中文，
  不要順手重排沒有動到的程式碼。
- 面向使用者、用來稱呼某個功能的字串，在已有先例的地方請改從設定讀取
  （參考 `cogs/points.py`）。

## 回報問題

請寫清楚你執行了什麼、發生了什麼、你預期的是什麼。附上 log 會很有幫助——
但貼上來之前請先把使用者 ID、token 和伺服器名稱塗掉。

---

# Contributing (English)

Thanks for taking a look. PRs and issues are both welcome, in English or Chinese.

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

- **`python -m compileall -q -x '(^|/)venv/' .` and `ruff check .` must both
  pass.** That's exactly what CI runs. The bot hot-reloads changed cogs in
  production within ~30s of a push to `main`, so a syntax error ships almost
  immediately.
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
