# -*- coding: utf-8 -*-
"""Unified scheduler: text messages + built-in actions, all cron-driven."""
from __future__ import annotations

import datetime
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Optional

import discord
from croniter import croniter
from discord.ext import commands, tasks

sys.path.append(os.path.abspath(".."))
from leetcode import (
    main as leetcode_main,
    get_link,
    get_description,
    get_upcoming_contests,
)

logger = logging.getLogger(__name__)

SCHEDULES_PATH = Path("json/scheduled_messages.json")
TZ = datetime.timezone(datetime.timedelta(hours=8))

ENTRY_TYPES = ("text", "leetcode_daily", "happy_birthday", "lol_reminder", "contest_check")
BUILTIN_TYPES = ("leetcode_daily", "happy_birthday", "lol_reminder", "contest_check")
TYPE_LABELS = {
    "text": "純文字",
    "leetcode_daily": "LeetCode 每日題",
    "happy_birthday": "生日提醒",
    "lol_reminder": "LOL 提醒",
    "contest_check": "LeetCode 比賽偵測",
}


def load_schedules() -> dict:
    if not SCHEDULES_PATH.exists():
        return {}
    try:
        with SCHEDULES_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def save_schedules(data: dict) -> None:
    SCHEDULES_PATH.parent.mkdir(exist_ok=True)
    with SCHEDULES_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def is_valid_cron(expr: str) -> bool:
    return bool(expr) and croniter.is_valid(expr)


def _parse_iso(ts: Optional[str]) -> datetime.datetime:
    if not ts:
        return datetime.datetime(1970, 1, 1, tzinfo=TZ)
    try:
        dt = datetime.datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt
    except ValueError:
        return datetime.datetime(1970, 1, 1, tzinfo=TZ)


def _chunk_text(text: str, limit: int) -> list[str]:
    chunks = []
    remaining = text
    while len(remaining) > limit:
        cut = remaining.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


# ── Built-in handlers ──

async def _handle_leetcode_daily(bot, channel, entry):
    result = leetcode_main()
    if isinstance(result, str):
        await channel.send(result)
        return
    thread = await channel.create_thread(
        name=result[0], message=None,
        auto_archive_duration=4320,
        type=discord.ChannelType.public_thread,
    )
    await thread.send(get_link())
    await thread.send("Difficulty: " + result[1])
    desc = get_description()
    if desc:
        for chunk in _chunk_text(desc, 1900):
            await thread.send(chunk)


async def _handle_happy_birthday(bot, channel, entry):
    cfg = bot.config
    for role_id in cfg["roles"]["birthday"]:
        await channel.send(f"<@&{role_id}>")
    await channel.send(f'<@&{cfg["roles"]["birthday_ping"]}> 生日快樂🎉')
    await channel.send("https://giphy.com/gifs/xTcnSSsbe4hhZBvV6M")


async def _handle_lol_reminder(bot, channel, entry):
    role_id = bot.config["roles"]["lol"]
    await channel.send(f"<@&{role_id}> 一把")


async def _handle_contest_check(bot, channel, entry, *, state):
    """state is a per-cog dict to remember which contests we've already handled."""
    now = datetime.datetime.now(datetime.timezone.utc)
    role_id = bot.config["roles"]["leetcode_contest"]
    contests = get_upcoming_contests()

    for c in contests:
        title = c["title"]
        start = c["start"]
        diff = (start - now).total_seconds()

        if 25 * 60 <= diff <= 35 * 60 and title not in state["reminded"]:
            state["reminded"].add(title)
            time_str = start.astimezone(TZ).strftime("%H:%M")
            await channel.send(
                f"<@&{role_id}> **{title}** 將在 30 分鐘後開始（{time_str}）！\n"
                f"https://leetcode.com/contest/"
            )
            logger.info("Contest reminder sent: %s", title)

        if -10 * 60 <= diff <= 0 and title not in state["threaded"]:
            state["threaded"].add(title)
            thread = await channel.create_thread(
                name=f"{title} 討論串",
                auto_archive_duration=4320,
                type=discord.ChannelType.public_thread,
            )
            await thread.send(
                f"**{title}** 已經開始！在這裡討論吧\n"
                f"https://leetcode.com/contest/"
            )
            logger.info("Contest thread created: %s", title)


HANDLERS = {
    "leetcode_daily": _handle_leetcode_daily,
    "happy_birthday": _handle_happy_birthday,
    "lol_reminder": _handle_lol_reminder,
    "contest_check": _handle_contest_check,
}


# Default seeds when scheduled_messages.json has no built-in entries yet.
SEED_SPECS = [
    ("leetcode_daily",  ("channels", "leetcode"), "5 8 * * *"),
    ("happy_birthday",  ("channels", "birthday"), "0 0 * * *"),
    ("lol_reminder",    ("channels", "lol"),      "0 23 * * *"),
    ("contest_check",   ("channels", "leetcode"), "*/5 * * * *"),
]


class Scheduled(commands.Cog):
    """Cron-driven scheduler for both user text messages and built-in actions."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._contest_state = {"reminded": set(), "threaded": set()}
        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

    def reload_now(self) -> int:
        return sum(len(v) for v in load_schedules().values())

    async def _seed_builtin_if_missing(self):
        data = load_schedules()
        already = {
            e.get("type")
            for entries in data.values()
            for e in entries
            if e.get("type") in BUILTIN_TYPES
        }
        missing = [s for s in SEED_SPECS if s[0] not in already]
        if not missing:
            return

        cfg = self.bot.config
        added = 0
        for type_, cfg_path, cron in missing:
            try:
                channel_id = cfg
                for k in cfg_path:
                    channel_id = channel_id[k]
            except (KeyError, TypeError):
                logger.warning("seed: config.yaml missing %s for %s", cfg_path, type_)
                continue
            try:
                channel = self.bot.get_channel(int(channel_id)) or await self.bot.fetch_channel(int(channel_id))
            except Exception as e:
                logger.warning("seed: cannot fetch channel %s: %s", channel_id, e)
                continue
            guild = getattr(channel, "guild", None)
            if guild is None:
                continue
            bucket = data.setdefault(str(guild.id), [])
            bucket.append({
                "id": uuid.uuid4().hex[:12],
                "channel_id": str(channel_id),
                "type": type_,
                "message": "",
                "cron": cron,
                "enabled": True,
                "last_fired": None,
            })
            added += 1
            logger.info("seeded built-in schedule: %s -> guild %s channel %s",
                        type_, guild.id, channel_id)
        if added:
            save_schedules(data)

    @commands.Cog.listener()
    async def on_ready(self):
        await self._seed_builtin_if_missing()

    async def _fire(self, entry: dict, channel) -> None:
        type_ = entry.get("type", "text")
        if type_ == "text":
            await channel.send(entry.get("message", ""))
            return
        handler = HANDLERS.get(type_)
        if handler is None:
            logger.warning("Unknown entry type: %s", type_)
            return
        if type_ == "contest_check":
            await handler(self.bot, channel, entry, state=self._contest_state)
        else:
            await handler(self.bot, channel, entry)

    @tasks.loop(seconds=30)
    async def tick(self):
        now = datetime.datetime.now(TZ)
        data = load_schedules()
        dirty = False

        for guild_id_str, entries in list(data.items()):
            for entry in entries:
                if not entry.get("enabled", True):
                    continue
                cron_expr = entry.get("cron")
                if not cron_expr or not is_valid_cron(cron_expr):
                    continue
                last = _parse_iso(entry.get("last_fired"))
                try:
                    next_fire = croniter(cron_expr, last).get_next(datetime.datetime)
                except Exception:
                    continue
                if next_fire.tzinfo is None:
                    next_fire = next_fire.replace(tzinfo=TZ)
                if now < next_fire:
                    continue

                channel_id = entry.get("channel_id")
                if not channel_id:
                    continue
                try:
                    channel = self.bot.get_channel(int(channel_id)) or await self.bot.fetch_channel(int(channel_id))
                except Exception as e:
                    logger.warning("Scheduled fire: cannot fetch channel %s: %s", channel_id, e)
                    entry["last_fired"] = now.isoformat()
                    dirty = True
                    continue

                try:
                    await self._fire(entry, channel)
                    logger.info(
                        "Scheduled fired: guild=%s entry=%s type=%s -> #%s",
                        guild_id_str, entry.get("id"), entry.get("type", "text"),
                        getattr(channel, "name", channel_id),
                    )
                except discord.HTTPException as e:
                    logger.error("Scheduled send failed: %s", e)
                except Exception as e:
                    logger.exception("Scheduled handler crashed: %s", e)

                entry["last_fired"] = now.isoformat()
                dirty = True

        if dirty:
            save_schedules(data)

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()

    @commands.command(name="test_contest", hidden=True)
    @commands.is_owner()
    async def test_contest(self, ctx: commands.Context):
        """測試比賽提醒和討論串（會發真的訊息，測完手動刪）"""
        channel = await self.bot.fetch_channel(self.bot.config["channels"]["leetcode"])
        role_id = self.bot.config["roles"]["leetcode_contest"]
        title = "Test Contest（測試用）"
        await channel.send(
            f"<@&{role_id}> **{title}** 將在 30 分鐘後開始（10:30）！\n"
            f"https://leetcode.com/contest/"
        )
        thread = await channel.create_thread(
            name=f"{title} 討論串",
            auto_archive_duration=60,
            type=discord.ChannelType.public_thread,
        )
        await thread.send(
            f"**{title}** 已經開始！在這裡討論吧\n"
            f"https://leetcode.com/contest/"
        )
        await ctx.send("測試完成，記得手動刪除訊息和討論串")


async def setup(bot: commands.Bot):
    await bot.add_cog(Scheduled(bot))
