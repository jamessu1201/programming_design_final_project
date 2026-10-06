# -*- coding: utf-8 -*-
"""把活躍度事件推到外部網站的 `POST /api/activity/batches`。

收什麼：
- 訊息：每則新訊息一筆（誰、哪個頻道、實際送出時間、回覆誰、字數、附件數）。不送內容。
  編輯不算新訊息、刪除不補送負數——API 是首次寫入為準。
- 語音：每分鐘掃一次語音頻道，同一次掃描共用同一個 `sampled_at`，每個真人一筆。
  固定口徑：排除 bot、排除 AFK 頻道（`include_afk: true` 可改），靜音/拒聽照樣算在線。

怎麼送：
- 事件先寫進持久化 outbox（SQLite，logs/activity_push/outbox.db），bot 重啟不會丟。
- 每 `upload_minutes` 分鐘把 outbox 依 guild 分批送出，一批最多 1,000 筆 / 1 MiB，
  有積壓就連續送到清空為止（批次間隔 1 秒，低於每分鐘 60 次的上限）。
- 200 才刪 outbox；逾時或 5xx/連線錯誤原樣重送（指數退避 + 隨機延遲）；429 至少等 60 秒；
  413 對半拆；422 整批移到 quarantine 表留著查，不會無限重送；401/403 記 log 等人修。
- `!activity_push status` 看積壓與最近結果；`!activity_push_backfill` 把 archive 的歷史訊息
  （cogs/archive.py 爬下來的）排進 outbox 補傳。

頻道名稱：另一個端點 `POST /api/activity/channels`，讓網站能把 channel_id 顯示成名字。
啟動時送全部，之後每 `upload_minutes` 分鐘只送有變的（改名/新頻道/新討論串會立刻送）；
archive 的 channels 表也會併進去，所以已封存討論串、被刪掉的頻道也有名字。

token：環境變數 `activity_push_token` 優先，否則讀 `api_key/activity_push.txt`。
預設關閉；config.yaml 的 `activity_push:` 區塊 `enabled: true` 才會動。
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import random
import sqlite3
import unicodedata
from typing import Optional

import aiohttp
import discord
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)

KEY_ENV = "activity_push_token"
KEY_FILE = "api_key/activity_push.txt"
OUTBOX_DB = os.path.join("logs", "activity_push", "outbox.db")
ENDPOINT = "/api/activity/batches"
CHANNELS_ENDPOINT = "/api/activity/channels"
NAME_MAX = 100

BATCH_MAX = 1000
BYTES_MAX = 1024 * 1024
BATCH_GAP_SECONDS = 1.0        # 連續送批次時的間隔（上限每分鐘 60 次）
RETRY_BASE = 30                # 5xx/連線錯誤：30s, 60s, 120s … 上限 RETRY_CAP
RETRY_CAP = 30 * 60
RATE_LIMIT_WAIT = 60
TZ = datetime.timezone(datetime.timedelta(hours=8))

DEFAULTS = {
    "enabled": False,
    "guild_id": None,          # None = 所有伺服器
    "base_url": "",            # 例：https://example.com（不含路徑）
    "include_afk": False,      # 語音取樣要不要算 AFK 頻道裡的人
    "upload_minutes": 5,
}


def push_config(bot) -> dict:
    cfg = dict(DEFAULTS)
    cfg.update((getattr(bot, "config", None) or {}).get("activity_push") or {})
    return cfg


def _guild_enabled(bot, guild_id) -> bool:
    cfg = push_config(bot)
    return bool(cfg["enabled"]) and (cfg["guild_id"] is None or guild_id == cfg["guild_id"])


def _load_token(env_name: str = KEY_ENV, path: str = KEY_FILE) -> Optional[str]:
    key = os.environ.get(env_name)
    if key:
        return key.strip()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip() or None
    except FileNotFoundError:
        return None


def _utcnow() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


# ── 事件 → API 欄位 ──

def message_event(m: discord.Message) -> dict:
    reply_to = None
    ref = getattr(m, "reference", None)
    resolved = getattr(ref, "resolved", None) if ref else None
    if isinstance(resolved, discord.Message):
        reply_to = str(resolved.author.id)
    return {
        "message_id": str(m.id),
        "user_id": str(m.author.id),
        "channel_id": str(m.channel.id),
        "sent_at": m.created_at.isoformat(),
        "reply_to_user_id": reply_to,
        "text_length": len(m.content or ""),
        "attachment_count": len(m.attachments),
    }


def voice_event(user_id: int, channel_id: int, sampled_at: str) -> dict:
    return {"user_id": str(user_id), "channel_id": str(channel_id), "sampled_at": sampled_at}


def sanitize_name(name: str) -> Optional[str]:
    """API 規則：去前後空白、不含控制字元、1–100 字；不合格回 None。"""
    cleaned = "".join(c for c in (name or "") if not unicodedata.category(c).startswith("C")).strip()
    if not cleaned:
        return None
    return cleaned[:NAME_MAX]


def live_channel_names(guild: discord.Guild) -> dict[int, str]:
    """現在看得到的、會出現在訊息/語音事件裡的頻道：文字、語音、舞台、論壇、活躍討論串。"""
    out: dict[int, str] = {}
    for ch in guild.channels:
        if isinstance(ch, discord.CategoryChannel):
            continue
        out[ch.id] = ch.name
    for th in guild.threads:
        out[th.id] = th.name
    return out


def archived_channel_names(guild_id: int) -> dict[int, str]:
    """archive（cogs/archive.py）的 channels 表：涵蓋已封存討論串、已刪頻道。沒有就空。"""
    try:
        from cogs import archive as archive_cog
    except ImportError:
        return {}
    if not os.path.exists(archive_cog.META_DB):
        return {}
    try:
        conn = sqlite3.connect(f"file:{archive_cog.META_DB}?mode=ro", uri=True)
        try:
            return {int(cid): name for cid, name in conn.execute(
                "SELECT channel_id, name FROM channels WHERE guild_id=?", (guild_id,))}
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning("activity_push: 讀 archive channels 失敗：%s", e)
        return {}


async def push_channels(session: aiohttp.ClientSession, base_url: str, token: str,
                        guild_id: int, rows: list[dict]) -> PushResult:
    """送一批頻道名稱（呼叫端保證 ≤ BATCH_MAX 筆）。"""
    if not rows:
        return PushResult("empty")
    data = json.dumps({"guild_id": str(guild_id), "channels": rows}, ensure_ascii=False).encode("utf-8")
    if len(data) > BYTES_MAX and len(rows) > 1:
        half = len(rows) // 2
        a = await push_channels(session, base_url, token, guild_id, rows[:half])
        if a.status != "ok":
            return a
        b = await push_channels(session, base_url, token, guild_id, rows[half:])
        return PushResult(b.status, sent=a.sent + b.sent, inserted=a.inserted + b.inserted,
                          duplicates=a.duplicates + b.duplicates, detail=b.detail)
    url = base_url.rstrip("/") + CHANNELS_ENDPOINT
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        async with session.post(url, data=data, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=60)) as resp:
            status = resp.status
            text = await resp.text()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        return PushResult("retry", sent=len(rows), detail=f"連線錯誤：{e}")
    if status == 200:
        try:
            j = json.loads(text)
            return PushResult("ok", sent=len(rows), inserted=int(j.get("updated", 0)),
                              duplicates=int(j.get("unchanged", 0)))
        except (ValueError, AttributeError, TypeError):
            return PushResult("ok", sent=len(rows))
    if status in (401, 403):
        return PushResult("auth", sent=len(rows), detail=f"{status} {text[:300]}")
    if status == 422:
        return PushResult("quarantined", sent=len(rows), detail=text[:500])
    if status == 429:
        return PushResult("retry", sent=len(rows), retry_after=RATE_LIMIT_WAIT, detail="429")
    return PushResult("retry", sent=len(rows), detail=f"{status} {text[:300]}")


# ── outbox（SQLite） ──

SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    kind       TEXT NOT NULL,          -- 'm' 訊息 / 'v' 語音取樣
    payload    TEXT NOT NULL,          -- JSON
    created_ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_outbox_guild ON outbox (guild_id, id);
CREATE TABLE IF NOT EXISTS quarantine (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id   INTEGER NOT NULL,
    kind       TEXT NOT NULL,
    payload    TEXT NOT NULL,
    error      TEXT NOT NULL,
    created_ts INTEGER NOT NULL
);
"""


class Outbox:
    def __init__(self, path: str = OUTBOX_DB):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    def add(self, rows: list[tuple]) -> None:
        """rows: (guild_id, kind, payload_dict)。"""
        if not rows:
            return
        now = int(_utcnow().timestamp())
        self.conn.executemany(
            "INSERT INTO outbox (guild_id, kind, payload, created_ts) VALUES (?,?,?,?)",
            [(g, k, json.dumps(p, ensure_ascii=False), now) for g, k, p in rows])
        self.conn.commit()

    def next_guild(self) -> Optional[int]:
        row = self.conn.execute("SELECT guild_id FROM outbox ORDER BY id LIMIT 1").fetchone()
        return int(row[0]) if row else None

    def fetch(self, guild_id: int, limit: int = BATCH_MAX) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT id, kind, payload FROM outbox WHERE guild_id=? ORDER BY id LIMIT ?",
            (guild_id, limit)).fetchall()

    def ack(self, ids: list[int]) -> None:
        if not ids:
            return
        self.conn.executemany("DELETE FROM outbox WHERE id=?", [(i,) for i in ids])
        self.conn.commit()

    def quarantine(self, rows: list[sqlite3.Row], guild_id: int, error: str) -> None:
        if not rows:
            return
        now = int(_utcnow().timestamp())
        self.conn.executemany(
            "INSERT INTO quarantine (guild_id, kind, payload, error, created_ts) VALUES (?,?,?,?,?)",
            [(guild_id, r["kind"], r["payload"], error[:2000], now) for r in rows])
        self.ack([r["id"] for r in rows])

    def counts(self) -> dict:
        pending = self.conn.execute(
            "SELECT kind, COUNT(*) FROM outbox GROUP BY kind").fetchall()
        q = self.conn.execute("SELECT COUNT(*) FROM quarantine").fetchone()[0]
        out = {"m": 0, "v": 0, "quarantine": q}
        for k, n in pending:
            out[k] = n
        oldest = self.conn.execute("SELECT MIN(created_ts) FROM outbox").fetchone()[0]
        out["oldest_ts"] = oldest
        return out


def build_body(guild_id: int, rows: list[sqlite3.Row]) -> dict:
    body: dict = {"guild_id": str(guild_id)}
    msgs = [json.loads(r["payload"]) for r in rows if r["kind"] == "m"]
    voices = [json.loads(r["payload"]) for r in rows if r["kind"] == "v"]
    if msgs:
        body["messages"] = msgs
    if voices:
        body["voice_samples"] = voices
    return body


def fit_batch(guild_id: int, rows: list[sqlite3.Row]) -> tuple[list[sqlite3.Row], bytes]:
    """把 rows 砍到 JSON 本體不超過 BYTES_MAX。回傳 (實際送的 rows, 編碼好的 body)。"""
    while True:
        data = json.dumps(build_body(guild_id, rows), ensure_ascii=False).encode("utf-8")
        if len(data) <= BYTES_MAX or len(rows) <= 1:
            return rows, data
        rows = rows[: max(1, len(rows) // 2)]


class PushResult:
    __slots__ = ("status", "sent", "inserted", "duplicates", "retry_after", "detail")

    def __init__(self, status: str, sent: int = 0, inserted: int = 0, duplicates: int = 0,
                 retry_after: float = 0.0, detail: str = ""):
        self.status = status          # ok / empty / retry / auth / quarantined / no_token
        self.sent = sent
        self.inserted = inserted
        self.duplicates = duplicates
        self.retry_after = retry_after
        self.detail = detail


async def push_one_batch(session: aiohttp.ClientSession, base_url: str, token: str,
                         outbox: Outbox, max_rows: int = BATCH_MAX) -> PushResult:
    """送 outbox 裡最早那個 guild 的一批。呼叫端負責退避與迴圈。"""
    guild_id = outbox.next_guild()
    if guild_id is None:
        return PushResult("empty")
    rows = outbox.fetch(guild_id, max_rows)
    rows, data = fit_batch(guild_id, rows)
    url = base_url.rstrip("/") + ENDPOINT
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    try:
        async with session.post(url, data=data, headers=headers,
                                timeout=aiohttp.ClientTimeout(total=60)) as resp:
            status = resp.status
            text = await resp.text()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        return PushResult("retry", sent=len(rows), detail=f"連線錯誤：{e}")

    if status == 200:
        try:
            j = json.loads(text)
            ins = (j.get("messages") or {}).get("inserted", 0) + \
                  (j.get("voice_samples") or {}).get("inserted", 0)
            dup = (j.get("messages") or {}).get("duplicates", 0) + \
                  (j.get("voice_samples") or {}).get("duplicates", 0)
        except (ValueError, AttributeError):
            ins = dup = 0
        outbox.ack([r["id"] for r in rows])
        return PushResult("ok", sent=len(rows), inserted=ins, duplicates=dup)
    if status in (401, 403):
        return PushResult("auth", sent=len(rows), detail=f"{status} {text[:300]}")
    if status == 413:
        # 伺服器嫌大但我們算起來沒超過 → 再對半砍一次重試
        if len(rows) > 1:
            return await push_one_batch(session, base_url, token, outbox, max(1, len(rows) // 2))
        outbox.quarantine(rows, guild_id, f"413 {text[:300]}")
        return PushResult("quarantined", sent=1, detail="單筆就超過 1 MiB")
    if status == 422:
        outbox.quarantine(rows, guild_id, f"422 {text[:1500]}")
        return PushResult("quarantined", sent=len(rows), detail=text[:300])
    if status == 429:
        return PushResult("retry", sent=len(rows), retry_after=RATE_LIMIT_WAIT,
                          detail="429 rate limited")
    return PushResult("retry", sent=len(rows), detail=f"{status} {text[:300]}")


# ── Cog ──

class ActivityPush(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._outbox: Optional[Outbox] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._upload_lock = asyncio.Lock()
        self._backoff = 0                       # 連續失敗次數
        self._blocked_until = 0.0               # unix 秒，之前不送
        self._last: str = "還沒送過"
        self._token_warned = 0.0
        self._sent_names: dict[int, dict[int, str]] = {}   # {guild_id: {channel_id: 上次送成功的名字}}
        self._names_last: str = "還沒送過"
        self.voice_tick.start()
        self.uploader.start()
        self.channel_sync.start()

    def cog_unload(self):
        self.voice_tick.cancel()
        self.uploader.cancel()
        self.channel_sync.cancel()
        if self._session:
            self.bot.loop.create_task(self._session.close())
        if self._outbox:
            self._outbox.close()

    def outbox(self) -> Outbox:
        if self._outbox is None:
            self._outbox = Outbox()
        return self._outbox

    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    # ── 收集 ──

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if not _guild_enabled(self.bot, message.guild.id):
            return
        try:
            self.outbox().add([(message.guild.id, "m", message_event(message))])
        except sqlite3.Error as e:
            logger.error("activity_push: outbox 寫入失敗：%s", e)

    @tasks.loop(seconds=60)
    async def voice_tick(self):
        cfg = push_config(self.bot)
        if not cfg["enabled"]:
            return
        sampled_at = _utcnow().isoformat()
        rows = []
        for guild in self.bot.guilds:
            if not _guild_enabled(self.bot, guild.id):
                continue
            afk_id = guild.afk_channel.id if guild.afk_channel else None
            for vc in guild.voice_channels:
                if vc.id == afk_id and not cfg["include_afk"]:
                    continue
                for m in vc.members:
                    if not m.bot:
                        rows.append((guild.id, "v", voice_event(m.id, vc.id, sampled_at)))
        if rows:
            try:
                self.outbox().add(rows)
            except sqlite3.Error as e:
                logger.error("activity_push: outbox 寫入失敗：%s", e)

    @voice_tick.before_loop
    async def before_voice_tick(self):
        await self.bot.wait_until_ready()

    @voice_tick.error
    async def voice_tick_error(self, error):
        logger.error("activity_push voice_tick error: %s", error)

    # ── 頻道名稱同步 ──

    @tasks.loop(minutes=DEFAULTS["upload_minutes"])
    async def channel_sync(self):
        # 第一次 tick 就是啟動時（送全部），之後每 upload_minutes 分鐘只送有變的。
        await self.sync_channel_names()

    @channel_sync.before_loop
    async def before_channel_sync(self):
        await self.bot.wait_until_ready()
        minutes = max(1, int(push_config(self.bot)["upload_minutes"]))
        if self.channel_sync.minutes != minutes:
            self.channel_sync.change_interval(minutes=minutes)

    @channel_sync.error
    async def channel_sync_error(self, error):
        logger.error("activity_push channel_sync error: %s", error)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if getattr(before, "name", None) != getattr(after, "name", None):
            await self._sync_if_enabled(after.guild.id)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await self._sync_if_enabled(channel.guild.id)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        await self._sync_if_enabled(thread.guild.id)

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        if before.name != after.name:
            await self._sync_if_enabled(after.guild.id)

    async def _sync_if_enabled(self, guild_id: int) -> None:
        if _guild_enabled(self.bot, guild_id):
            await self.sync_channel_names(only_guild=guild_id)

    async def sync_channel_names(self, only_guild: Optional[int] = None, force: bool = False) -> None:
        """把名字有變的頻道送到 /api/activity/channels；force=True 送全部。"""
        cfg = push_config(self.bot)
        if not cfg["enabled"]:
            return
        base_url = (cfg.get("base_url") or "").strip()
        token = _load_token()
        if not base_url or not token:
            return   # drain 那邊會每小時提醒一次，這裡不重複
        if self._blocked_until > _utcnow().timestamp():
            return
        async with self._upload_lock:   # 跟批次上傳共用同一條 60 次/分的額度
            session = await self.session()
            observed_at = _utcnow().isoformat()
            for guild in self.bot.guilds:
                if only_guild is not None and guild.id != only_guild:
                    continue
                if not _guild_enabled(self.bot, guild.id):
                    continue
                names = archived_channel_names(guild.id)
                names.update(live_channel_names(guild))   # 現在的名字優先
                sent = self._sent_names.setdefault(guild.id, {})
                rows = []
                for cid, raw in names.items():
                    name = sanitize_name(raw)
                    if name is None or (not force and sent.get(cid) == name):
                        continue
                    rows.append({"channel_id": str(cid), "name": name, "observed_at": observed_at})
                if not rows:
                    continue
                ok = True
                for i in range(0, len(rows), BATCH_MAX):
                    chunk = rows[i:i + BATCH_MAX]
                    r = await push_channels(session, base_url, token, guild.id, chunk)
                    if r.status == "ok":
                        for row in chunk:
                            sent[int(row["channel_id"])] = row["name"]
                        self._names_last = (f"{_utcnow().astimezone(TZ):%m-%d %H:%M} 送 {r.sent} 個頻道名："
                                            f"更新 {r.inserted}、沒變 {r.duplicates}")
                        logger.info("activity_push: %s", self._names_last)
                    else:
                        ok = False
                        self._names_last = f"{_utcnow().astimezone(TZ):%m-%d %H:%M} 頻道名稱送失敗：{r.detail}"
                        logger.warning("activity_push: %s", self._names_last)
                        if r.status == "quarantined":
                            # 422：整批裡有不合規的名字；下次 tick 會再試，先不卡其他 guild
                            pass
                        break
                    if i + BATCH_MAX < len(rows):
                        await asyncio.sleep(BATCH_GAP_SECONDS)
                if not ok:
                    continue

    # ── 上傳 ──

    @tasks.loop(seconds=60)
    async def uploader(self):
        cfg = push_config(self.bot)
        if not cfg["enabled"]:
            return
        now = _utcnow().timestamp()
        # 沒積壓時照 upload_minutes 的節奏；有退避就等退避到。
        if now < self._blocked_until:
            return
        if self.uploader.current_loop % max(1, int(cfg["upload_minutes"])) != 0 and self._backoff == 0:
            return
        await self.drain()

    @uploader.before_loop
    async def before_uploader(self):
        await self.bot.wait_until_ready()

    @uploader.error
    async def uploader_error(self, error):
        logger.error("activity_push uploader error: %s", error)

    async def drain(self) -> None:
        """連續送到 outbox 清空或遇到要等的狀況。同時只會有一個在跑。"""
        if self._upload_lock.locked():
            return
        async with self._upload_lock:
            cfg = push_config(self.bot)
            base_url = (cfg.get("base_url") or "").strip()
            token = _load_token()
            if not base_url or not token:
                now = _utcnow().timestamp()
                if now - self._token_warned > 3600:
                    self._token_warned = now
                    logger.warning("activity_push: 缺 base_url 或 token（%s / %s），先不送",
                                   "config activity_push.base_url", KEY_FILE)
                self._last = "缺 base_url 或 token"
                return
            session = await self.session()
            outbox = self.outbox()
            while True:
                r = await push_one_batch(session, base_url, token, outbox)
                if r.status == "empty":
                    self._backoff = 0
                    return
                if r.status == "ok":
                    self._backoff = 0
                    self._last = (f"{_utcnow().astimezone(TZ):%m-%d %H:%M} 送 {r.sent} 筆："
                                  f"新增 {r.inserted}、重複 {r.duplicates}")
                    logger.info("activity_push: %s", self._last)
                    await asyncio.sleep(BATCH_GAP_SECONDS)
                    continue
                if r.status == "quarantined":
                    self._last = f"{_utcnow().astimezone(TZ):%m-%d %H:%M} {r.sent} 筆被退（422/413）→ quarantine"
                    logger.warning("activity_push: %s：%s", self._last, r.detail)
                    await asyncio.sleep(BATCH_GAP_SECONDS)
                    continue
                if r.status == "auth":
                    self._last = f"{_utcnow().astimezone(TZ):%m-%d %H:%M} 認證失敗：{r.detail}"
                    logger.error("activity_push: %s", self._last)
                    self._blocked_until = _utcnow().timestamp() + RETRY_CAP
                    return
                # retry：指數退避 + 隨機
                self._backoff += 1
                wait = r.retry_after or min(RETRY_CAP, RETRY_BASE * 2 ** (self._backoff - 1))
                wait += random.uniform(0, wait * 0.25)
                self._blocked_until = _utcnow().timestamp() + wait
                self._last = f"{_utcnow().astimezone(TZ):%m-%d %H:%M} 失敗（{r.detail}），{wait:.0f}s 後重試"
                logger.warning("activity_push: %s", self._last)
                return

    # ── 指令（限 owner） ──

    @commands.command(name="activity_push", hidden=True)
    @commands.is_owner()
    async def activity_push_cmd(self, ctx: commands.Context, action: str = "status"):
        """`!activity_push status` 看積壓；`!activity_push now` 立刻送一輪；
        `!activity_push channels` 重送全部頻道名稱。"""
        action = action.lower()
        if action == "now":
            self._blocked_until = 0
            self._backoff = 0
            await ctx.send("⏫ 開始送…")
            await self.drain()
            await self.sync_channel_names()
        elif action == "channels":
            self._blocked_until = 0
            await ctx.send("📛 重送全部頻道名稱…")
            await self.sync_channel_names(force=True)
        c = self.outbox().counts()
        oldest = (f"，最舊 {datetime.datetime.fromtimestamp(c['oldest_ts'], TZ):%m-%d %H:%M}"
                  if c.get("oldest_ts") else "")
        blocked = ""
        if self._blocked_until > _utcnow().timestamp():
            blocked = f"\n⏸ 退避中，{self._blocked_until - _utcnow().timestamp():.0f}s 後再試"
        await ctx.send(
            f"📤 activity_push\n待送：訊息 {c['m']:,}、語音取樣 {c['v']:,}{oldest}\n"
            f"隔離（422/413）：{c['quarantine']:,}\n最近：{self._last}\n"
            f"頻道名稱：{self._names_last}{blocked}")

    @commands.command(name="activity_push_backfill", hidden=True)
    @commands.is_owner()
    @commands.guild_only()
    async def activity_push_backfill(self, ctx: commands.Context, from_date: str = ""):
        """把 archive（cogs/archive.py）裡這個伺服器的歷史訊息排進 outbox 補傳。

        `!activity_push_backfill`             全部
        `!activity_push_backfill 2026-01-01`  只補這天（含）之後的
        回覆對象用 archive 的 reply_to_id 對回作者（舊資料要先 `!archive_backfill rescan`）。
        伺服器會去重，但它是首次寫入為準：已存在的列不會被更新。
        """
        if not _guild_enabled(self.bot, ctx.guild.id):
            return await ctx.send("此功能未在這個伺服器啟用（config.yaml `activity_push.enabled`）。")
        try:
            from cogs import archive as archive_cog
        except ImportError:
            return await ctx.send("找不到 archive cog。")
        start_ts = 0
        if from_date:
            try:
                d = datetime.date.fromisoformat(from_date)
            except ValueError:
                return await ctx.send("日期請用 `YYYY-MM-DD`。")
            start_ts = int(datetime.datetime.combine(d, datetime.time.min, TZ).timestamp())
        if not os.path.exists(archive_cog.META_DB):
            return await ctx.send(f"還沒有 archive 資料（{archive_cog.META_DB}），先 `!archive_backfill`。")
        src = sqlite3.connect(archive_cog.META_DB)
        src.row_factory = sqlite3.Row
        total = 0
        batch = []
        outbox = self.outbox()
        status = await ctx.send("📦 從 archive 排入 outbox…")
        try:
            with_reply = 0
            for r in src.execute(
                    "SELECT m.message_id, m.channel_id, m.user_id, m.ts, m.attachments, m.length,"
                    " p.user_id AS reply_to FROM messages m"
                    " LEFT JOIN messages p ON p.message_id = m.reply_to_id"
                    " WHERE m.guild_id=? AND m.ts>=? AND m.deleted_ts IS NULL ORDER BY m.message_id",
                    (ctx.guild.id, start_ts)):
                sent_at = datetime.datetime.fromtimestamp(r["ts"], datetime.timezone.utc).isoformat()
                reply_to = r["reply_to"]
                if reply_to is not None:
                    with_reply += 1
                batch.append((ctx.guild.id, "m", {
                    "message_id": str(r["message_id"]), "user_id": str(r["user_id"]),
                    "channel_id": str(r["channel_id"]), "sent_at": sent_at,
                    "reply_to_user_id": str(reply_to) if reply_to is not None else None,
                    "text_length": int(r["length"]), "attachment_count": int(r["attachments"]),
                }))
                if len(batch) >= 5000:
                    outbox.add(batch)
                    total += len(batch)
                    batch = []
                    await asyncio.sleep(0)   # 讓 event loop 喘口氣
                    if total % 50_000 == 0:
                        try:
                            await status.edit(content=f"📦 已排入 {total:,} 筆…")
                        except discord.HTTPException:
                            pass
            outbox.add(batch)
            total += len(batch)
        finally:
            src.close()
        await ctx.send(f"✅ 已把 {total:,} 筆歷史訊息排進 outbox（{with_reply:,} 筆帶回覆對象），"
                       f"上傳器會依序送出"
                       f"（每批 1,000 筆、每秒一批，約 {total / 1000 / 60:.0f} 分鐘）。"
                       f"`!activity_push status` 看進度。")
        self._blocked_until = 0
        asyncio.create_task(self.drain())


async def setup(bot):
    await bot.add_cog(ActivityPush(bot))
