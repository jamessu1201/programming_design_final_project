# -*- coding: utf-8 -*-
"""訊息封存：每則訊息的 metadata 存進 SQLite，之後可以直接查「某人在某段時間講了幾句」。

兩個檔案，故意分開：
- logs/archive/messages.db  metadata（誰、何時、哪個頻道、幾個附件、幾個字）+ 頻道/使用者
                            名稱對照 + 回填進度。統計全靠這個。
- logs/archive/content.db   message_id → 內容與附件 URL。只有 `store_content: true` 才寫；
                            不想留內容就關掉或直接刪檔，統計不受影響。

來源：
- 即時：on_message 寫入、編輯/刪除會更新（刪除只標記，不真的刪）。
- 回填：`!archive_backfill`（限 owner）把每個頻道（含討論串、論壇貼文）從最舊的訊息爬到
  現在。進度存在 DB，中斷後重跑會從每個頻道上次的位置接著爬；按 message_id 去重所以
  重跑永遠安全。bot 訊息一律不收。

查詢：`/archive stats`、`/archive top`、`/archive status`，dashboard 也有同樣的頁面；
檔案本身是普通 SQLite，拿 DB Browser / pandas 開也行。

預設關閉；config.yaml 的 `archive:` 區塊 `enabled: true` 才會動。時間一律 UTC+8 顯示，
DB 裡存 unix 秒。
"""
from __future__ import annotations

import asyncio
import datetime
import json
import logging
import os
import sqlite3
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)

ARCHIVE_DIR = os.path.join("logs", "archive")
META_DB = os.path.join(ARCHIVE_DIR, "messages.db")
CONTENT_DB = os.path.join(ARCHIVE_DIR, "content.db")

TZ = datetime.timezone(datetime.timedelta(hours=8))
TZ_SQL = "+8 hours"          # 給 strftime 用，跟 TZ 要一致
FLUSH_SECONDS = 10           # 即時訊息先排隊，每隔這麼久寫一次
BACKFILL_BATCH = 500         # 回填每 N 則寫一次 + 存進度
DEFAULT_DAYS = 30
TOP_SIZE = 15
WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]

DEFAULTS = {
    "enabled": False,        # 預設不收：這是在存群友什麼時候講了話，拿去用的人自己決定
    "guild_id": None,        # None = 所有伺服器
    "store_content": False,  # True 才把訊息內容另外存到 content.db
}


def archive_config(bot) -> dict:
    cfg = dict(DEFAULTS)
    cfg.update((getattr(bot, "config", None) or {}).get("archive") or {})
    return cfg


def archive_enabled(bot, guild_id) -> bool:
    cfg = archive_config(bot)
    return bool(cfg["enabled"]) and (cfg["guild_id"] is None or guild_id == cfg["guild_id"])


# ── 日期區間 ──

def parse_range(frm: Optional[str], to: Optional[str],
                now: Optional[datetime.datetime] = None) -> tuple[int, int, str]:
    """把 YYYY-MM-DD（含）轉成 unix 秒區間。省略 = 最近 DEFAULT_DAYS 天到今天。

    回傳 (start_ts, end_ts, 顯示用字串)；日期格式錯丟 ValueError。
    """
    now = now or datetime.datetime.now(TZ)
    end_d = datetime.date.fromisoformat(to.strip()) if to else now.date()
    start_d = (datetime.date.fromisoformat(frm.strip()) if frm
               else end_d - datetime.timedelta(days=DEFAULT_DAYS - 1))
    if start_d > end_d:
        raise ValueError("起日晚於迄日")
    start = datetime.datetime.combine(start_d, datetime.time.min, TZ)
    end = datetime.datetime.combine(end_d, datetime.time.max, TZ)
    return int(start.timestamp()), int(end.timestamp()), f"{start_d} ~ {end_d}"


def _bar(n: int, peak: int, width: int = 12) -> str:
    if peak <= 0 or n <= 0:
        return ""
    return "█" * max(1, round(n / peak * width))


# ── SQLite 層（同步；單列寫入 < 1ms，批次用 executemany） ──

META_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    message_id  INTEGER PRIMARY KEY,
    guild_id    INTEGER NOT NULL,
    channel_id  INTEGER NOT NULL,
    user_id     INTEGER NOT NULL,
    ts          INTEGER NOT NULL,
    attachments INTEGER NOT NULL DEFAULT 0,
    length      INTEGER NOT NULL DEFAULT 0,
    edited_ts   INTEGER,
    deleted_ts  INTEGER,
    reply_to_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_msg_guild_user_ts ON messages (guild_id, user_id, ts);
CREATE INDEX IF NOT EXISTS idx_msg_guild_chan_ts ON messages (guild_id, channel_id, ts);
CREATE INDEX IF NOT EXISTS idx_msg_guild_ts ON messages (guild_id, ts);
CREATE TABLE IF NOT EXISTS channels (
    channel_id INTEGER PRIMARY KEY,
    guild_id   INTEGER NOT NULL,
    name       TEXT NOT NULL,
    parent_id  INTEGER,
    kind       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    username     TEXT NOT NULL,
    display_name TEXT NOT NULL,
    updated_ts   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS backfill (
    channel_id      INTEGER PRIMARY KEY,
    guild_id        INTEGER NOT NULL,
    last_message_id INTEGER,
    scanned         INTEGER NOT NULL DEFAULT 0,
    done            INTEGER NOT NULL DEFAULT 0,
    updated_ts      INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS rescan (
    channel_id      INTEGER PRIMARY KEY,
    last_message_id INTEGER,
    done            INTEGER NOT NULL DEFAULT 0
);
"""

# 舊檔沒有的欄位在開檔時補上（ADD COLUMN 不會動到既有資料）
META_MIGRATIONS = [("messages", "reply_to_id", "INTEGER")]

CONTENT_SCHEMA = """
CREATE TABLE IF NOT EXISTS content (
    message_id  INTEGER PRIMARY KEY,
    content     TEXT NOT NULL,
    attachments TEXT NOT NULL DEFAULT '[]'
);
"""


def _connect(path: str, schema: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # WAL + NORMAL：bot 與 dashboard 同 process 共用檔案沒問題，而且每次 commit
    # 不用等 fsync（HDD bind 上差很多）。壞掉最多丟最後幾秒。
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.executescript(schema)
    if schema is META_SCHEMA:
        for table, col, typ in META_MIGRATIONS:
            cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
            if col not in cols:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typ}")
                conn.commit()
    return conn


class ArchiveDB:
    """兩個 SQLite 檔的薄包裝。內容檔只在 store_content 時開。"""

    def __init__(self, meta_path: str = META_DB, content_path: str = CONTENT_DB,
                 store_content: bool = False):
        self.meta = _connect(meta_path, META_SCHEMA)
        self.content = _connect(content_path, CONTENT_SCHEMA) if store_content else None
        self.meta_path = meta_path
        self.content_path = content_path

    def close(self) -> None:
        self.meta.close()
        if self.content is not None:
            self.content.close()

    # 寫入

    def upsert_messages(self, rows: list[tuple]) -> None:
        """rows: (message_id, guild_id, channel_id, user_id, ts, attachments, length, edited_ts,
        reply_to_id)。已存在的列只更新會變的欄位（編輯時間/長度/附件數/回覆對象）。"""
        if not rows:
            return
        self.meta.executemany(
            "INSERT INTO messages (message_id, guild_id, channel_id, user_id, ts, attachments,"
            " length, edited_ts, reply_to_id) VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(message_id) DO UPDATE SET attachments=excluded.attachments,"
            " length=excluded.length, edited_ts=excluded.edited_ts,"
            " reply_to_id=COALESCE(excluded.reply_to_id, messages.reply_to_id)", rows)
        self.meta.commit()

    def upsert_content(self, rows: list[tuple]) -> None:
        """rows: (message_id, content, attachments_json)。"""
        if self.content is None or not rows:
            return
        self.content.executemany(
            "INSERT INTO content (message_id, content, attachments) VALUES (?,?,?)"
            " ON CONFLICT(message_id) DO UPDATE SET content=excluded.content,"
            " attachments=excluded.attachments", rows)
        self.content.commit()

    def mark_edited(self, message_id: int, edited_ts: int, length: Optional[int],
                    content: Optional[str]) -> None:
        if length is None:
            self.meta.execute("UPDATE messages SET edited_ts=? WHERE message_id=?",
                              (edited_ts, message_id))
        else:
            self.meta.execute("UPDATE messages SET edited_ts=?, length=? WHERE message_id=?",
                              (edited_ts, length, message_id))
        self.meta.commit()
        if content is not None and self.content is not None:
            self.content.execute("UPDATE content SET content=? WHERE message_id=?",
                                 (content, message_id))
            self.content.commit()

    def mark_deleted(self, message_ids: list[int], deleted_ts: int) -> None:
        if not message_ids:
            return
        self.meta.executemany("UPDATE messages SET deleted_ts=? WHERE message_id=?",
                              [(deleted_ts, m) for m in message_ids])
        self.meta.commit()

    def upsert_channels(self, rows: list[tuple]) -> None:
        """rows: (channel_id, guild_id, name, parent_id, kind)。"""
        if not rows:
            return
        self.meta.executemany(
            "INSERT INTO channels (channel_id, guild_id, name, parent_id, kind) VALUES (?,?,?,?,?)"
            " ON CONFLICT(channel_id) DO UPDATE SET name=excluded.name,"
            " parent_id=excluded.parent_id, kind=excluded.kind", rows)
        self.meta.commit()

    def upsert_users(self, rows: list[tuple]) -> None:
        """rows: (user_id, username, display_name, updated_ts)。只讓較新的名字蓋過去。"""
        if not rows:
            return
        self.meta.executemany(
            "INSERT INTO users (user_id, username, display_name, updated_ts) VALUES (?,?,?,?)"
            " ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,"
            " display_name=excluded.display_name, updated_ts=excluded.updated_ts"
            " WHERE excluded.updated_ts >= users.updated_ts", rows)
        self.meta.commit()

    # 回填進度

    def backfill_state(self, channel_id: int) -> Optional[sqlite3.Row]:
        return self.meta.execute("SELECT * FROM backfill WHERE channel_id=?",
                                 (channel_id,)).fetchone()

    def save_backfill(self, channel_id: int, guild_id: int, last_message_id: Optional[int],
                      scanned: int, done: bool, now_ts: int) -> None:
        self.meta.execute(
            "INSERT INTO backfill (channel_id, guild_id, last_message_id, scanned, done, updated_ts)"
            " VALUES (?,?,?,?,?,?) ON CONFLICT(channel_id) DO UPDATE SET"
            " last_message_id=excluded.last_message_id, scanned=excluded.scanned,"
            " done=excluded.done, updated_ts=excluded.updated_ts",
            (channel_id, guild_id, last_message_id, scanned, int(done), now_ts))
        self.meta.commit()

    def rescan_state(self, channel_id: int) -> Optional[sqlite3.Row]:
        return self.meta.execute("SELECT * FROM rescan WHERE channel_id=?", (channel_id,)).fetchone()

    def save_rescan(self, channel_id: int, last_message_id: Optional[int], done: bool) -> None:
        self.meta.execute(
            "INSERT INTO rescan (channel_id, last_message_id, done) VALUES (?,?,?)"
            " ON CONFLICT(channel_id) DO UPDATE SET last_message_id=excluded.last_message_id,"
            " done=excluded.done", (channel_id, last_message_id, int(done)))
        self.meta.commit()

    def clear_rescan(self) -> None:
        self.meta.execute("DELETE FROM rescan")
        self.meta.commit()

    def reply_coverage(self, guild_id: int) -> tuple[int, int]:
        """(是回覆的則數, 其中回覆對象也在 archive 裡的則數)。"""
        row = self.meta.execute(
            "SELECT COUNT(*), COALESCE(SUM(EXISTS (SELECT 1 FROM messages r"
            " WHERE r.message_id=m.reply_to_id)), 0)"
            " FROM messages m WHERE m.guild_id=? AND m.reply_to_id IS NOT NULL", (guild_id,)).fetchone()
        return int(row[0]), int(row[1])

    def backfill_summary(self, guild_id: int) -> dict:
        row = self.meta.execute(
            "SELECT COUNT(*) AS sources, SUM(done) AS done, SUM(scanned) AS scanned,"
            " MAX(updated_ts) AS updated FROM backfill WHERE guild_id=?", (guild_id,)).fetchone()
        return dict(row) if row else {}

    # 查詢

    def overview(self, guild_id: int) -> dict:
        row = self.meta.execute(
            "SELECT COUNT(*) AS n, MIN(ts) AS first_ts, MAX(ts) AS last_ts,"
            " COUNT(DISTINCT user_id) AS users, COUNT(DISTINCT channel_id) AS channels"
            " FROM messages WHERE guild_id=?", (guild_id,)).fetchone()
        out = dict(row)
        out["content_rows"] = (self.content.execute("SELECT COUNT(*) FROM content").fetchone()[0]
                               if self.content is not None else None)
        out["meta_bytes"] = os.path.getsize(self.meta_path) if os.path.exists(self.meta_path) else 0
        out["content_bytes"] = (os.path.getsize(self.content_path)
                                if os.path.exists(self.content_path) else 0)
        return out

    def user_stats(self, guild_id: int, user_id: int, start: int, end: int) -> dict:
        """某人在區間內：總數、各頻道、24 小時分布、星期分布、有幾天有講話。"""
        where = "m.guild_id=? AND m.user_id=? AND m.ts BETWEEN ? AND ? AND m.deleted_ts IS NULL"
        args = (guild_id, user_id, start, end)
        total = self.meta.execute(f"SELECT COUNT(*) FROM messages m WHERE {where}", args).fetchone()[0]
        per_channel = self.meta.execute(
            f"SELECT m.channel_id, COALESCE(c.name, '#' || m.channel_id) AS name, COUNT(*) AS n"
            f" FROM messages m LEFT JOIN channels c USING (channel_id)"
            f" WHERE {where} GROUP BY m.channel_id ORDER BY n DESC", args).fetchall()
        hours = [0] * 24
        for h, n in self.meta.execute(
                f"SELECT CAST(strftime('%H', m.ts, 'unixepoch', '{TZ_SQL}') AS INTEGER), COUNT(*)"
                f" FROM messages m WHERE {where} GROUP BY 1", args):
            hours[h] = n
        weekdays = [0] * 7   # index: 0=週一 … 6=週日（strftime %w 是 0=週日）
        for w, n in self.meta.execute(
                f"SELECT CAST(strftime('%w', m.ts, 'unixepoch', '{TZ_SQL}') AS INTEGER), COUNT(*)"
                f" FROM messages m WHERE {where} GROUP BY 1", args):
            weekdays[(w + 6) % 7] = n
        active_days = self.meta.execute(
            f"SELECT COUNT(DISTINCT date(m.ts, 'unixepoch', '{TZ_SQL}')) FROM messages m WHERE {where}",
            args).fetchone()[0]
        return {"total": total, "per_channel": [dict(r) for r in per_channel],
                "hours": hours, "weekdays": weekdays, "active_days": active_days}

    def top_users(self, guild_id: int, start: int, end: int, limit: int = TOP_SIZE,
                  channel_id: Optional[int] = None) -> list[dict]:
        where = "m.guild_id=? AND m.ts BETWEEN ? AND ? AND m.deleted_ts IS NULL"
        args: list = [guild_id, start, end]
        if channel_id is not None:
            where += " AND m.channel_id=?"
            args.append(channel_id)
        rows = self.meta.execute(
            f"SELECT m.user_id, COALESCE(u.display_name, u.username, m.user_id) AS name,"
            f" COUNT(*) AS n FROM messages m LEFT JOIN users u USING (user_id)"
            f" WHERE {where} GROUP BY m.user_id ORDER BY n DESC LIMIT ?", (*args, limit)).fetchall()
        return [dict(r) for r in rows]

    def known_users(self, guild_id: int) -> list[dict]:
        rows = self.meta.execute(
            "SELECT u.user_id, COALESCE(u.display_name, u.username) AS name"
            " FROM users u WHERE EXISTS (SELECT 1 FROM messages m WHERE m.user_id=u.user_id"
            " AND m.guild_id=?) ORDER BY name COLLATE NOCASE", (guild_id,)).fetchall()
        return [dict(r) for r in rows]


# ── 共用：把 discord 物件轉成列 ──

def _reply_to_id(m: discord.Message) -> Optional[int]:
    """被回覆的 message_id；轉發、討論串起始訊息之類的不算。"""
    ref = getattr(m, "reference", None)
    if ref is None or m.type is not discord.MessageType.reply:
        return None
    return ref.message_id


def _message_rows(m: discord.Message):
    ts = int(m.created_at.timestamp())
    edited = int(m.edited_at.timestamp()) if m.edited_at else None
    meta = (m.id, m.guild.id, m.channel.id, m.author.id, ts,
            len(m.attachments), len(m.content or ""), edited, _reply_to_id(m))
    content = (m.id, m.content or "", json.dumps([a.url for a in m.attachments]))
    return meta, content


def _channel_row(ch) -> tuple:
    parent = getattr(ch, "parent_id", None)
    kind = type(ch).__name__.replace("Channel", "").lower() or "channel"
    return (ch.id, ch.guild.id, getattr(ch, "name", str(ch.id)), parent, kind)


def _user_row(author, now_ts: int) -> tuple:
    return (author.id, author.name, getattr(author, "display_name", author.name), now_ts)


def _utcnow_ts() -> int:
    return int(datetime.datetime.now(datetime.timezone.utc).timestamp())


async def iter_history_sources(guild: discord.Guild):
    """所有掃得到歷史的地方：文字/語音頻道、它們的討論串（含已封存）、論壇貼文。"""
    for ch in list(guild.text_channels) + list(guild.voice_channels):
        yield ch
        for th in getattr(ch, "threads", ()):
            yield th
        if hasattr(ch, "archived_threads"):
            try:
                async for th in ch.archived_threads(limit=None):
                    yield th
            except (discord.Forbidden, discord.HTTPException):
                pass
    for fch in getattr(guild, "forums", ()):
        for th in fch.threads:
            yield th
        try:
            async for th in fch.archived_threads(limit=None):
                yield th
        except (discord.Forbidden, discord.HTTPException):
            pass


# ── Cog ──

class Archive(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._db: Optional[ArchiveDB] = None
        self._pending_meta: list[tuple] = []
        self._pending_content: list[tuple] = []
        self._pending_users: dict[int, tuple] = {}
        self._pending_channels: dict[int, tuple] = {}
        self._seen_users: dict[int, tuple] = {}     # 名字沒變就不重寫
        self._seen_channels: dict[int, tuple] = {}
        self._backfill_task: Optional[asyncio.Task] = None
        self.flush.start()

    def cog_unload(self):
        self.flush.cancel()
        if self._backfill_task:
            self._backfill_task.cancel()
        self._flush_now()
        if self._db:
            self._db.close()

    group = app_commands.Group(name="archive", description="訊息統計（誰在什麼時候講了幾句）",
                               guild_only=True)

    def db(self) -> ArchiveDB:
        """DB 連線跟著 config 走，所以 !reload 後 store_content 變了也會生效。"""
        want_content = bool(archive_config(self.bot)["store_content"])
        if self._db is None or (self._db.content is not None) != want_content:
            if self._db is not None:
                self._db.close()
            self._db = ArchiveDB(store_content=want_content)
        return self._db

    # ── 即時寫入 ──

    def _queue_message(self, m: discord.Message) -> None:
        meta, content = _message_rows(m)
        self._pending_meta.append(meta)
        self._pending_content.append(content)
        u = _user_row(m.author, _utcnow_ts())
        if self._seen_users.get(m.author.id) != u[1:3]:
            self._seen_users[m.author.id] = u[1:3]
            self._pending_users[m.author.id] = u
        c = _channel_row(m.channel)
        if self._seen_channels.get(m.channel.id) != c[2:]:
            self._seen_channels[m.channel.id] = c[2:]
            self._pending_channels[m.channel.id] = c

    def _flush_now(self) -> None:
        if not (self._pending_meta or self._pending_users or self._pending_channels):
            return
        db = self.db()
        meta, self._pending_meta = self._pending_meta, []
        content, self._pending_content = self._pending_content, []
        users, self._pending_users = list(self._pending_users.values()), {}
        channels, self._pending_channels = list(self._pending_channels.values()), {}
        try:
            db.upsert_channels(channels)
            db.upsert_users(users)
            db.upsert_messages(meta)
            db.upsert_content(content)
        except sqlite3.Error as e:
            logger.error("archive: 寫入失敗，丟掉 %d 則：%s", len(meta), e)

    @tasks.loop(seconds=FLUSH_SECONDS)
    async def flush(self):
        self._flush_now()

    @flush.before_loop
    async def before_flush(self):
        await self.bot.wait_until_ready()
        if archive_config(self.bot)["enabled"]:
            self.db()   # 一開機就開檔：schema 遷移馬上做掉，壞掉也早點在 log 看到

    @flush.error
    async def flush_error(self, error):
        logger.error("archive flush error: %s", error)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if not archive_enabled(self.bot, message.guild.id):
            return
        self._queue_message(message)

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        if not payload.guild_id or not archive_enabled(self.bot, payload.guild_id):
            return
        data = payload.data
        if data.get("author", {}).get("bot"):
            return
        edited = data.get("edited_timestamp")
        if not edited:
            return   # 只是 embed 展開之類的，不算編輯
        edited_ts = int(datetime.datetime.fromisoformat(edited).timestamp())
        content = data.get("content")   # 部分更新時可能沒有
        self._flush_now()   # 確保原始那列已經在 DB 裡
        try:
            self.db().mark_edited(payload.message_id, edited_ts,
                                  len(content) if content is not None else None, content)
        except sqlite3.Error as e:
            logger.error("archive: 更新編輯失敗：%s", e)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent):
        if not payload.guild_id or not archive_enabled(self.bot, payload.guild_id):
            return
        self._mark_deleted([payload.message_id])

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload: discord.RawBulkMessageDeleteEvent):
        if not payload.guild_id or not archive_enabled(self.bot, payload.guild_id):
            return
        self._mark_deleted(list(payload.message_ids))

    def _mark_deleted(self, ids: list[int]) -> None:
        self._flush_now()
        try:
            self.db().mark_deleted(ids, _utcnow_ts())
        except sqlite3.Error as e:
            logger.error("archive: 標記刪除失敗：%s", e)

    # ── 回填 ──

    def _backfill_running(self) -> bool:
        return self._backfill_task is not None and not self._backfill_task.done()

    @commands.command(name="archive_backfill", hidden=True)
    @commands.is_owner()
    @commands.guild_only()
    async def archive_backfill(self, ctx: commands.Context, mode: str = ""):
        """把整個伺服器的歷史訊息爬進 archive。

        `!archive_backfill`        從每個頻道上次的位置接著爬（第一次 = 從最舊開始）
        `!archive_backfill rescan` 全部重掃一次（補舊資料缺的欄位，例如回覆對象）；可中斷續傳
        `!archive_backfill stop`   停掉正在跑的
        `!archive_backfill status` 看進度
        """
        if not archive_enabled(self.bot, ctx.guild.id):
            return await ctx.send("此功能未在這個伺服器啟用（config.yaml `archive.enabled`）。")
        mode = mode.lower()
        if mode == "stop":
            if not self._backfill_running():
                return await ctx.send("沒有在跑的回填。")
            self._backfill_task.cancel()
            return await ctx.send("🛑 已送出停止，當前批次寫完就會停；之後重跑會接著爬。")
        if mode == "status":
            return await ctx.send(self._status_text(ctx.guild.id))
        if self._backfill_running():
            return await ctx.send("已經有一個回填在跑，`!archive_backfill status` 看進度。")
        self._backfill_task = asyncio.create_task(
            self._backfill_run(ctx, rescan=(mode == "rescan")))

    def _status_text(self, guild_id: int) -> str:
        db = self.db()
        ov = db.overview(guild_id)
        bf = db.backfill_summary(guild_id)
        running = "，**跑步中**" if self._backfill_running() else ""
        lines = [f"📦 archive：{ov['n'] or 0:,} 則訊息、{ov['users'] or 0} 人、"
                 f"{ov['channels'] or 0} 個頻道"]
        if ov.get("first_ts"):
            first = datetime.datetime.fromtimestamp(ov["first_ts"], TZ).strftime("%Y-%m-%d")
            last = datetime.datetime.fromtimestamp(ov["last_ts"], TZ).strftime("%Y-%m-%d %H:%M")
            lines.append(f"範圍：{first} ~ {last}")
        size = f"messages.db {ov['meta_bytes'] / 1024 / 1024:.1f} MB"
        if ov["content_rows"] is not None:
            size += (f"、content.db {ov['content_bytes'] / 1024 / 1024:.1f} MB"
                     f"（{ov['content_rows']:,} 則）")
        else:
            size += "（未存內容）"
        lines.append(size)
        replies, resolvable = db.reply_coverage(guild_id)
        if replies:
            lines.append(f"回覆：{replies:,} 則是回覆，其中 {resolvable:,} 則的對象在 archive 裡")
        if bf.get("sources"):
            lines.append(f"回填：{bf['done'] or 0}/{bf['sources']} 個來源完成，"
                         f"共讀過 {bf['scanned'] or 0:,} 則{running}")
        else:
            lines.append(f"回填：還沒跑過（`!archive_backfill`）{running}")
        return "\n".join(lines)

    async def _backfill_run(self, ctx: commands.Context, rescan: bool = False):
        guild = ctx.guild
        db = self.db()
        status = await ctx.send(
            ("🔁 開始重掃全部歷史…" if rescan else "🔎 開始爬歷史訊息…")
            + "（量大時要跑很久，`!archive_backfill status` 看進度）")
        scanned_total = stored_total = sources = skipped = 0
        started = datetime.datetime.now(TZ)

        try:
            async for source in iter_history_sources(guild):
                sources += 1
                name = getattr(source, "name", source.id)
                state = db.backfill_state(source.id)
                scanned = int(state["scanned"]) if state else 0
                if rescan:
                    # 重掃用自己的進度表：從頭讀，但中斷後能接著；正常進度表只會往前推。
                    rs = db.rescan_state(source.id)
                    if rs and rs["done"]:
                        continue
                    last_id = rs["last_message_id"] if rs else None
                    final_id = state["last_message_id"] if state else None
                else:
                    last_id = state["last_message_id"] if state else None
                    final_id = None
                after = discord.Object(id=last_id) if last_id else None
                db.upsert_channels([_channel_row(source)])
                meta: list[tuple] = []
                content: list[tuple] = []
                users: dict[int, tuple] = {}

                def write_batch(done: bool):
                    nonlocal meta, content, users
                    db.upsert_users(list(users.values()))
                    db.upsert_messages(meta)
                    db.upsert_content(content)
                    meta, content, users = [], [], {}
                    if rescan:
                        db.save_rescan(source.id, last_id, done)
                        if last_id and (final_id is None or last_id > final_id):
                            db.save_backfill(source.id, guild.id, last_id, scanned, True, _utcnow_ts())
                    else:
                        db.save_backfill(source.id, guild.id, last_id, scanned, done, _utcnow_ts())

                try:
                    async for m in source.history(limit=None, after=after, oldest_first=True):
                        if not rescan:
                            scanned += 1
                        scanned_total += 1
                        last_id = m.id
                        if not m.author.bot:
                            mr, cr = _message_rows(m)
                            meta.append(mr)
                            content.append(cr)
                            # 用訊息時間當名字的時間戳，這樣回填不會把現在的名字蓋成舊的
                            users[m.author.id] = _user_row(m.author, int(m.created_at.timestamp()))
                            stored_total += 1
                        if len(meta) >= BACKFILL_BATCH:
                            write_batch(False)
                        if scanned_total % 20_000 == 0:
                            logger.info("archive backfill: 已讀 %s 則，目前在 #%s", scanned_total, name)
                            try:
                                await status.edit(
                                    content=f"🔎 爬取中…已讀 {scanned_total:,} 則（目前 #{name}）")
                            except discord.HTTPException:
                                pass
                except (discord.Forbidden, discord.HTTPException) as e:
                    skipped += 1
                    logger.warning("archive backfill: 略過 #%s：%s", name, e)
                    write_batch(False)
                    continue
                write_batch(True)
        except asyncio.CancelledError:
            await ctx.send(f"🛑 已停止：這次讀了 {scanned_total:,} 則、存了 {stored_total:,} 則。"
                           f"重跑 `!archive_backfill` 會從各頻道的進度接著爬。")
            return
        except Exception:
            logger.exception("archive backfill 失敗")
            await ctx.send("❌ 回填中途出錯，看 log。進度已存，可以直接重跑。")
            return

        if rescan:
            db.clear_rescan()
        took = datetime.datetime.now(TZ) - started
        word = "重掃" if rescan else "回填"
        await ctx.send(
            f"✅ **{word}完成**（{took.seconds // 60} 分鐘）\n"
            f"掃了 {sources} 個頻道/討論串，這次讀了 {scanned_total:,} 則、新增/更新 {stored_total:,} 則"
            + (f"，{skipped} 個沒權限略過" if skipped else "") + "\n" + self._status_text(guild.id))

    # ── 查詢指令 ──

    async def _range_or_reply(self, interaction: discord.Interaction, frm, to):
        try:
            return parse_range(frm, to)
        except ValueError as e:
            await interaction.response.send_message(
                f"日期請用 `YYYY-MM-DD`，例如 `2026-01-01`。（{e}）", ephemeral=True)
            return None

    @group.command(name="stats", description="某人在一段時間內講了幾句、在哪、幾點")
    @app_commands.describe(user="要查誰（預設自己）",
                           from_date=f"起日 YYYY-MM-DD（預設最近 {DEFAULT_DAYS} 天）",
                           to_date="迄日 YYYY-MM-DD（預設今天）")
    @app_commands.rename(from_date="from", to_date="to")
    async def stats(self, interaction: discord.Interaction, user: Optional[discord.Member] = None,
                    from_date: Optional[str] = None, to_date: Optional[str] = None):
        if not archive_enabled(self.bot, interaction.guild_id):
            return await interaction.response.send_message("此功能未在這個伺服器啟用。", ephemeral=True)
        rng = await self._range_or_reply(interaction, from_date, to_date)
        if rng is None:
            return
        start, end, label = rng
        target = user or interaction.user
        self._flush_now()
        s = self.db().user_stats(interaction.guild_id, target.id, start, end)
        if not s["total"]:
            return await interaction.response.send_message(
                f"**{target.display_name}** 在 {label} 沒有訊息紀錄。", ephemeral=True)

        embed = discord.Embed(title=f"💬 {target.display_name} · {label}",
                              color=discord.Color.blurple())
        embed.description = (f"共 **{s['total']:,}** 則，{s['active_days']} 天有講話"
                             f"（平均每天 {s['total'] / max(s['active_days'], 1):.1f} 則）")
        chans = s["per_channel"]
        chan_text = "\n".join(f"#{c['name']}：{c['n']:,}" for c in chans[:8])
        if len(chans) > 8:
            chan_text += f"\n…還有 {len(chans) - 8} 個"
        embed.add_field(name="頻道", value=chan_text, inline=False)
        peak = max(s["hours"])
        hour_lines = [f"`{h:02d}` {_bar(n, peak)} {n}" for h, n in enumerate(s["hours"]) if n]
        embed.add_field(name="幾點講（UTC+8）", value="\n".join(hour_lines)[:1024], inline=True)
        wpeak = max(s["weekdays"])
        embed.add_field(name="星期", inline=True, value="\n".join(
            f"`週{WEEKDAY_NAMES[i]}` {_bar(n, wpeak, 8)} {n}" for i, n in enumerate(s["weekdays"])))
        await interaction.response.send_message(
            embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="top", description="一段時間內誰講最多話")
    @app_commands.describe(from_date=f"起日 YYYY-MM-DD（預設最近 {DEFAULT_DAYS} 天）",
                           to_date="迄日 YYYY-MM-DD（預設今天）", channel="只看某個頻道")
    @app_commands.rename(from_date="from", to_date="to")
    async def top(self, interaction: discord.Interaction, from_date: Optional[str] = None,
                  to_date: Optional[str] = None, channel: Optional[discord.TextChannel] = None):
        if not archive_enabled(self.bot, interaction.guild_id):
            return await interaction.response.send_message("此功能未在這個伺服器啟用。", ephemeral=True)
        rng = await self._range_or_reply(interaction, from_date, to_date)
        if rng is None:
            return
        start, end, label = rng
        self._flush_now()
        rows = self.db().top_users(interaction.guild_id, start, end,
                                   channel_id=channel.id if channel else None)
        if not rows:
            return await interaction.response.send_message(f"{label} 沒有訊息紀錄。", ephemeral=True)
        total = sum(r["n"] for r in rows)
        lines = [f"**{i}.** {r['name']}：{r['n']:,}" for i, r in enumerate(rows, start=1)]
        title = f"🏆 講話排行 · {label}" + (f" · #{channel.name}" if channel else "")
        embed = discord.Embed(title=title, description="\n".join(lines), color=discord.Color.gold())
        embed.set_footer(text=f"前 {len(rows)} 名合計 {total:,} 則")
        await interaction.response.send_message(
            embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="status", description="archive 收了多少、回填進度")
    async def status(self, interaction: discord.Interaction):
        if not archive_enabled(self.bot, interaction.guild_id):
            return await interaction.response.send_message("此功能未在這個伺服器啟用。", ephemeral=True)
        self._flush_now()
        await interaction.response.send_message(self._status_text(interaction.guild_id), ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction,
                                    error: app_commands.AppCommandError):
        logger.error("archive command error: %s", error)
        msg = f"發生錯誤：{error}"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Archive(bot))
