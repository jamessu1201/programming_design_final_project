# 安全性政策 / Security Policy

*(English below.)*

## 回報漏洞

安全性問題請**不要**開公開的 issue。

請改用 GitHub 的私下回報：**Security** 分頁 → *Report a vulnerability*。
這會開一則只有維護者看得到的私密 advisory。

寫的時候有幫助的資訊：攻擊者能做到什麼、你手上最小的重現步驟、牽涉到哪些檔案。
貼任何東西之前，請先把 token、使用者 ID 和伺服器名稱塗掉。

## 適用範圍

這是一隻自架的機器人，所以大部分的攻擊面其實屬於架設它的人。
本 repo 程式碼中屬於範圍內的問題：

- 任何能讓非 owner 碰到 owner 專屬指令或後台路由的問題。
- 後台的授權缺陷（OAuth 處理、session cookie、CSRF）。
- 會把 `api_key/`、`private/` 或 `config.yaml` 的內容洩漏到 Discord 訊息、
  log 或 HTTP 回應裡的程式碼路徑。
- 讓不受信任的輸入能執行 shell 指令或讀取任意檔案的指令處理邏輯。

不在範圍內：自己把 token 公開出去的部署、架設者自己挑了容易猜的 ntfy topic、
以及任何需要攻擊者「已經是 bot owner」才成立的問題。

## 如果你要架這隻機器人

- `api_key/`、`private/` 和 `config.yaml` 不要進 git——它們都有被 gitignore，
  但 commit 前還是先看一下 `git status`。
- `private/owners.txt` 只放你信得過的人；owner 可以執行 `!deploy` 和清除資料。
- 不要把後台直接裸露在外，前面要有一層 proxy。`api_key/oauth.json` 預設綁
  `127.0.0.1` 是刻意的。
- bot token 一旦出現在 commit、截圖或 log 裡，請立刻重新產生一組。
  Discord 偵測到公開外流的 token 也會自行作廢它。

---

# Security Policy (English)

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
