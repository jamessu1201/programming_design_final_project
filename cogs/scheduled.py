# -*- coding: utf-8 -*-
"""User-defined scheduled messages, fired by cron expressions."""
from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path
from typing import Optional

import discord
from croniter import croniter
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)

SCHEDULES_PATH = Path("json/scheduled_messages.json")
TZ = datetime.timezone(datetime.timedelta(hours=8))


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


class Scheduled(commands.Cog):
    """Fires user-defined scheduled messages based on cron schedules."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._data = load_schedules()
        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

    def reload_now(self) -> int:
        """Re-read schedules from disk; return total entry count."""
        self._data = load_schedules()
        return sum(len(v) for v in self._data.values())

    @tasks.loop(seconds=30)
    async def tick(self):
        now = datetime.datetime.now(TZ)
        # always re-read so dashboard edits take effect within one tick
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
                    channel = self.bot.get_channel(int(channel_id))
                    if channel is None:
                        channel = await self.bot.fetch_channel(int(channel_id))
                except Exception as e:
                    logger.warning("Scheduled fire: cannot fetch channel %s: %s", channel_id, e)
                    entry["last_fired"] = now.isoformat()
                    dirty = True
                    continue

                try:
                    await channel.send(entry.get("message", ""))
                    logger.info(
                        "Scheduled fired: guild=%s entry=%s -> #%s",
                        guild_id_str, entry.get("id"), getattr(channel, "name", channel_id),
                    )
                except discord.HTTPException as e:
                    logger.error("Scheduled send failed: %s", e)

                entry["last_fired"] = now.isoformat()
                dirty = True

        if dirty:
            save_schedules(data)
            self._data = data

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(Scheduled(bot))
