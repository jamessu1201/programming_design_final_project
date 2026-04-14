# -*- coding: utf-8 -*-
import logging
import random
import datetime

import discord
from discord.ext import commands, tasks

import os
import sys
sys.path.append(os.path.abspath(".."))
from leetcode import main as leetcode_main, get_link, get_description, get_upcoming_contests

logger = logging.getLogger(__name__)

UTC_PLUS_8 = datetime.timezone(datetime.timedelta(hours=8))
BIRTHDAY_TIME = datetime.time(hour=0, minute=0, tzinfo=UTC_PLUS_8)
LEETCODE_TIME = datetime.time(hour=8, minute=5, tzinfo=UTC_PLUS_8)


def _chunk_text(text, limit):
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


class Auto(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cfg = bot.config
        self._reminded_contests = set()
        self._threaded_contests = set()
        self.happy_birthday.start()
        self.leetcode.start()
        self.lol_reminder.start()
        self.contest_check.start()

    def cog_unload(self):
        self.happy_birthday.cancel()
        self.leetcode.cancel()
        self.lol_reminder.cancel()
        self.contest_check.cancel()

    # ── LeetCode Contest ──

    @tasks.loop(minutes=5)
    async def contest_check(self):
        now = datetime.datetime.now(datetime.timezone.utc)
        contests = get_upcoming_contests()
        channel = await self.bot.fetch_channel(self.cfg["channels"]["leetcode"])
        role_id = self.cfg["roles"]["leetcode_contest"]

        for c in contests:
            title = c["title"]
            start = c["start"]
            diff = (start - now).total_seconds()

            # 30 min reminder (trigger when 25~35 min before)
            if 25 * 60 <= diff <= 35 * 60 and title not in self._reminded_contests:
                self._reminded_contests.add(title)
                start_local = start.astimezone(UTC_PLUS_8)
                time_str = start_local.strftime("%H:%M")
                await channel.send(
                    f"<@&{role_id}> **{title}** 將在 30 分鐘後開始（{time_str}）！\n"
                    f"https://leetcode.com/contest/"
                )
                logger.info("Contest reminder sent: %s", title)

            # Create discussion thread (trigger when contest just started, 0~10 min after)
            if -10 * 60 <= diff <= 0 and title not in self._threaded_contests:
                self._threaded_contests.add(title)
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

    @commands.command(name="test_contest", hidden=True)
    @commands.is_owner()
    async def test_contest(self, ctx: commands.Context):
        """測試比賽提醒和討論串（會發真的訊息，測完手動刪）"""
        channel = await self.bot.fetch_channel(self.cfg["channels"]["leetcode"])
        role_id = self.cfg["roles"]["leetcode_contest"]
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

    @contest_check.before_loop
    async def before_contest_check(self):
        await self.bot.wait_until_ready()

    # ── LeetCode Daily ──

    @tasks.loop(time=LEETCODE_TIME)
    async def leetcode(self):
        logger.info("leetcode time")
        channel = await self.bot.fetch_channel(self.cfg["channels"]["leetcode"])
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
        description = get_description()
        if description:
            for chunk in _chunk_text(description, 1900):
                await thread.send(chunk)

    @leetcode.before_loop
    async def before_leetcode(self):
        await self.bot.wait_until_ready()

    # ── Birthday ──

    @tasks.loop(time=BIRTHDAY_TIME)
    async def happy_birthday(self):
        channel = await self.bot.fetch_channel(self.cfg["channels"]["birthday"])
        for role_id in self.cfg["roles"]["birthday"]:
            await channel.send(f"<@&{role_id}>")
        await channel.send(f'<@&{self.cfg["roles"]["birthday_ping"]}> 生日快樂🎉')
        await channel.send("https://giphy.com/gifs/xTcnSSsbe4hhZBvV6M")

    @happy_birthday.before_loop
    async def before_happy_birthday(self):
        await self.bot.wait_until_ready()

    # ── LOL ──

    @tasks.loop(hours=24)
    async def lol_reminder(self):
        channel = await self.bot.fetch_channel(self.cfg["channels"]["lol"])
        await channel.send(f'<@&{self.cfg["roles"]["lol"]}> 一把')

    @lol_reminder.before_loop
    async def before_lol_reminder(self):
        await self.bot.wait_until_ready()
        now = datetime.datetime.now(UTC_PLUS_8)
        rand_minute = random.randint(0, 59)
        target = now.replace(hour=23, minute=rand_minute, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)
        delta = (target - now).total_seconds()
        logger.info("LOL reminder scheduled in %.0f seconds (23:%02d)", delta, rand_minute)
        await discord.utils.sleep_until(target)


async def setup(bot):
    await bot.add_cog(Auto(bot))
