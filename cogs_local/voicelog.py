# -*- coding: utf-8 -*-
"""語音在線紀錄（私有 cog）。points.py 只存每天的語音點數，看不出「幾點、在哪、跟誰」。

兩種資料都放在 bind 的 logs/voice/ 底下（logs/ 整個被 gitignore，不用動 .gitignore）：

- logs/voice/<guild_id>.events.jsonl
    on_voice_state_update 的事件流：join / leave / move / mute / unmute / deaf / undeaf，
    每筆帶時間、頻道、當下頻道裡幾個真人。要算精確的進出時間、待在哪個頻道就看這個。
- logs/voice/<guild_id>.hourly.json
    {user_id: {"YYYY-MM-DD HH": {"m": 在線分鐘, "a": 活躍分鐘}}}
    每分鐘掃一次語音頻道累加；"a" 的條件比照 points（非 AFK 頻道、沒自己靜音/拒聽、
    頻道至少兩個真人）。bot 重啟不會像事件流那樣漏掉 leave，所以統計用這份比較穩。

時間一律 UTC+8。記憶體累積、每 FLUSH_MINUTES 分鐘落地一次（比照 points 的每日明細）。
"""
from __future__ import annotations

import datetime
import json
import logging
import os

import discord
from discord.ext import commands, tasks

import storage

logger = logging.getLogger(__name__)

VOICE_DIR = os.path.join("logs", "voice")
TZ = datetime.timezone(datetime.timedelta(hours=8))
FLUSH_MINUTES = 5


def _now() -> datetime.datetime:
    return datetime.datetime.now(TZ)


def _hour_key(now: datetime.datetime) -> str:
    return now.strftime("%Y-%m-%d %H")


def _hourly_path(guild_id) -> str:
    return os.path.join(VOICE_DIR, f"{guild_id}.hourly.json")


def _events_path(guild_id) -> str:
    return os.path.join(VOICE_DIR, f"{guild_id}.events.jsonl")


def _humans(channel) -> list:
    return [m for m in channel.members if not m.bot]


def _events_between(before: discord.VoiceState, after: discord.VoiceState) -> list[str]:
    """一次 voice_state_update 可能同時改好幾個欄位，全部列出來。"""
    events = []
    if before.channel is None and after.channel is not None:
        events.append("join")
    elif before.channel is not None and after.channel is None:
        events.append("leave")
    elif before.channel != after.channel:
        events.append("move")
    if before.self_mute != after.self_mute:
        events.append("mute" if after.self_mute else "unmute")
    if before.self_deaf != after.self_deaf:
        events.append("deaf" if after.self_deaf else "undeaf")
    return events


class VoiceLog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._pending: dict = {}   # {guild_id: {user_id: {hour_key: {"m": n, "a": n}}}}
        self.tick.start()
        self.flush.start()

    def cog_unload(self):
        self.tick.cancel()
        self.flush.cancel()
        if self._pending:
            self.bot.loop.create_task(self._flush_now())

    # ── 事件流 ──

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member,
                                    before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        events = _events_between(before, after)
        if not events:
            return  # 伺服器端靜音、開關視訊/直播之類的不記
        channel = after.channel or before.channel
        record = {
            "ts": _now().isoformat(timespec="seconds"),
            "user_id": str(member.id),
            "username": member.name,
            "display_name": member.display_name,
            "events": events,
            "channel_id": str(after.channel.id) if after.channel else None,
            "channel_name": after.channel.name if after.channel else None,
            "from_channel_id": str(before.channel.id) if before.channel else None,
            "from_channel_name": before.channel.name if before.channel else None,
            "self_mute": after.self_mute,
            "self_deaf": after.self_deaf,
            "humans_in_channel": len(_humans(channel)) if channel else 0,
        }
        try:
            os.makedirs(VOICE_DIR, exist_ok=True)
            with open(_events_path(member.guild.id), "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            logger.error("voicelog: 寫事件失敗：%s", e)

    # ── 每分鐘在線快照 → 小時桶 ──

    @tasks.loop(seconds=60)
    async def tick(self):
        now = _now()
        key = _hour_key(now)
        for guild in self.bot.guilds:
            afk_id = guild.afk_channel.id if guild.afk_channel else None
            per_user = self._pending.setdefault(str(guild.id), {})
            for vc in guild.voice_channels:
                humans = _humans(vc)
                if not humans:
                    continue
                channel_ok = vc.id != afk_id and len(humans) >= 2
                for m in humans:
                    vs = m.voice
                    active = channel_ok and vs is not None and not vs.self_mute and not vs.self_deaf
                    bucket = per_user.setdefault(str(m.id), {}).setdefault(key, {"m": 0, "a": 0})
                    bucket["m"] += 1
                    if active:
                        bucket["a"] += 1

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()

    @tick.error
    async def tick_error(self, error):
        logger.error("voicelog tick error: %s", error)

    @tasks.loop(minutes=FLUSH_MINUTES)
    async def flush(self):
        await self._flush_now()

    @flush.before_loop
    async def before_flush(self):
        await self.bot.wait_until_ready()

    @flush.error
    async def flush_error(self, error):
        logger.error("voicelog flush error: %s", error)

    async def _flush_now(self) -> None:
        pending, self._pending = self._pending, {}
        for guild_id, users in pending.items():
            if not users:
                continue
            path = _hourly_path(guild_id)
            async with storage.lock_for(path):
                data = storage.read_json(path)
                for uid, hours in users.items():
                    dst = data.setdefault(uid, {})
                    for key, b in hours.items():
                        cur = dst.setdefault(key, {"m": 0, "a": 0})
                        cur["m"] += b["m"]
                        cur["a"] += b["a"]
                storage.write_json_atomic(path, data)


async def setup(bot):
    await bot.add_cog(VoiceLog(bot))
