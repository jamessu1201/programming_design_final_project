# -*- coding: utf-8 -*-
import logging
import discord
from discord.ext import commands
import asyncio
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
    async def poll(self, ctx: commands.Context, topic, c1, c2, duration):
        """投票(主題 選項一 選項二 持續時間)"""
        emb = discord.Embed(
            title=topic,
            description=f":one:{c1}\n\n:two:{c2}",
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        emb.set_footer(text=f"由{ctx.author.name}發起投票")
        msg = await ctx.channel.send(embed=emb)
        await msg.add_reaction("1️⃣")
        await msg.add_reaction("2️⃣")
        await asyncio.sleep(int(duration))

        newmessage = await ctx.fetch_message(msg.id)
        one_count = 0
        two_count = 0
        for reaction in newmessage.reactions:
            if str(reaction.emoji) == "1️⃣":
                one_count = reaction.count - 1
            elif str(reaction.emoji) == "2️⃣":
                two_count = reaction.count - 1

        if one_count > two_count:
            result = c1
        elif two_count > one_count:
            result = c2
        else:
            result = "平手"
        emb = discord.Embed(
            title=topic,
            description=f"投票結果:{result}",
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await newmessage.edit(embed=emb)

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
