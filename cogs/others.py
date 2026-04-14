# -*- coding: utf-8 -*-
import logging
import re
import discord
from discord.ext import commands
import random
import datetime
import json
from pathlib import Path

logger = logging.getLogger(__name__)

PREFIX_JSON = "json/prefix.json"
BADWORD_JSON = "json/badword.json"


class Other(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await ctx.send("An error occurred: {}".format(str(error)))

    @commands.command(name="count")
    async def _count(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        """語音頻道人數"""
        if channel is None:
            await ctx.send("請輸入語音頻道")
            return
        count = sum(1 for m in channel.members if not m.bot)
        await ctx.send(f"目前{channel.name}裡面有{count}人")

    @commands.command(name="unbanwords")
    # @commands.has_permissions(manage_guild=True)
    async def _unbanwords(self, ctx: commands.Context, word: str = None):
        """解ban特定的字"""
        if word is None:
            await ctx.send("請輸入要解ban的單字")
            return
        with open(Path(BADWORD_JSON), "r", encoding="utf-8") as f:
            words = json.load(f)
        guild_id = str(ctx.guild.id)
        if guild_id in words:
            if word in words[guild_id]:
                words[guild_id].remove(word)
                if len(words[guild_id]) == 0:
                    del words[guild_id]
                with open(Path(BADWORD_JSON), "w", encoding="utf-8") as r:
                    json.dump(words, r)
                await ctx.send("設定成功!")
                return
            await ctx.send("這個詞沒有被ban過喔!")
        else:
            await ctx.send("沒有被ban的單字喔!")

    @commands.command(name="banwords")
    # @commands.has_permissions(manage_guild=True)
    async def _banwords(self, ctx: commands.Context, word=None):
        """ban特定的字"""
        if word is None:
            await ctx.send("請輸入要ban的單字")
            return
        with open(Path(BADWORD_JSON), "r", encoding="utf-8") as f:
            words = json.load(f)
        guild_id = str(ctx.guild.id)
        if guild_id not in words:
            words[guild_id] = word.split()
            with open(Path(BADWORD_JSON), "w", encoding="utf-8") as r:
                json.dump(words, r)
            await ctx.send("設定成功!")
        else:
            for w in words[guild_id]:
                if w == word:
                    await ctx.send("已經ban過了喔!")
                    return
            words[guild_id].extend(word.split())
            with open(Path(BADWORD_JSON), "w", encoding="utf-8") as r:
                json.dump(words, r)
            await ctx.send("設定成功!")

    @commands.command(name="banwordlist")
    # @commands.has_permissions(manage_guild=True)
    async def _banwordlist(self, ctx: commands.Context):
        """banlist"""
        with open(Path(BADWORD_JSON), "r", encoding="utf-8") as f:
            words = json.load(f)
        guild_id = str(ctx.guild.id)
        if guild_id not in words:
            await ctx.send("目前還沒禁任何文字")
            return
        for w in words[guild_id]:
            await ctx.send(w)

    @commands.command(name="test")
    @commands.guild_only()
    async def test(self, ctx: commands.Context):
        """test"""
        cfg = self.bot.config
        channel = await self.bot.fetch_channel(cfg["channels"]["leetcode"])
        await channel.create_thread(
            name="測試", auto_archive_duration=4320,
            type=discord.ChannelType.public_thread,
        )

    @commands.command(name="poll")
    @commands.guild_only()
    async def poll(self, ctx: commands.Context, *, raw: str = None):
        """投票：!poll 問題 | 選項1 | 選項2 | ... [| 6h] [| multi]

        用 | 或 ｜ 分隔問題和選項，最少 2 個、最多 10 個選項。
        結尾可加 `6h` 指定持續時間（預設 24 小時，最長 768 小時）。
        結尾可加 `multi` 或 `多選` 允許一人勾多個選項。
        使用 Discord 原生 Poll，會自動到期並顯示結果。
        """
        if not raw:
            return await ctx.send(
                "用法: `!poll 問題 | 選項1 | 選項2 | ... [| 6h] [| multi]`"
            )

        parts = [p.strip() for p in raw.replace("｜", "|").split("|") if p.strip()]

        hours = 24
        multi = False
        while parts:
            tail = parts[-1].lower()
            m = re.fullmatch(r"(\d+)\s*h(?:ours?)?", tail)
            if m:
                hours = int(m.group(1))
                parts.pop()
                continue
            if tail in ("multi", "multiple", "多選"):
                multi = True
                parts.pop()
                continue
            break

        if len(parts) < 3:
            return await ctx.send("至少需要 1 個問題和 2 個選項。")

        question, *options = parts
        if len(options) > 10:
            return await ctx.send("最多 10 個選項。")
        if not 1 <= hours <= 768:
            return await ctx.send("持續時間必須介於 1–768 小時。")
        if len(question) > 300:
            return await ctx.send("問題最長 300 字。")
        for opt in options:
            if len(opt) > 55:
                return await ctx.send(f"選項「{opt}」超過 55 字上限。")

        poll = discord.Poll(
            question=question,
            duration=datetime.timedelta(hours=hours),
            multiple=multi,
        )
        for opt in options:
            poll.add_answer(text=opt)

        try:
            await ctx.send(poll=poll)
        except discord.HTTPException as e:
            logger.error("Poll send failed: %s", e)
            await ctx.send(f"發送投票失敗：{e}")

    @commands.command(name="prefix")
    @commands.guild_only()
    async def setprefix(self, ctx, *, prefixes=""):
        """設定前綴"""
        if prefixes == "":
            await ctx.send("please enter the prefix.")
            return
        with open(PREFIX_JSON, "r", encoding="utf-8") as f:
            custom_prefixes = json.load(f)
        custom_prefixes[str(ctx.guild.id)] = prefixes
        with open(PREFIX_JSON, "w", encoding="utf-8") as r:
            json.dump(custom_prefixes, r)
        await ctx.send("Prefix was set to {} ".format(prefixes))

    @commands.command(name="draw")
    async def draw(self, ctx: commands.Context, number: int, channel: discord.VoiceChannel = None):
        """抽獎(要抽的數量 在哪個頻道抽)"""
        if channel is None:
            await ctx.send("請輸入語音頻道")
            return
        non_bot_members = [m for m in channel.members if not m.bot]
        if number > len(non_bot_members):
            await ctx.send("人數小於要抽的數目")
            return
        winners = random.sample(non_bot_members, number)
        await ctx.send("恭喜")
        for winner in winners:
            await ctx.send(winner.name)


async def setup(bot):
    await bot.add_cog(Other(bot))
