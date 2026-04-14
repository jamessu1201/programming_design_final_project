# -*- coding: utf-8 -*-
import re
import string
import logging
import random

import discord
from discord.ext import commands
import json
from unicodedata import lookup

logger = logging.getLogger(__name__)

BADWORD_JSON = "json/badword.json"
AUTO_REPLIES_JSON = "json/auto_replies.json"
REPLIES_STATE_JSON = "json/replies_state.json"


def _load_auto_replies():
    try:
        with open(AUTO_REPLIES_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logger.warning("auto_replies.json not found, meme replies disabled")
        return []


def _load_replies_state():
    """Load per-guild on/off state. Returns dict like {"guild_id": true/false}"""
    try:
        with open(REPLIES_STATE_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def _save_replies_state(state):
    with open(REPLIES_STATE_JSON, "w", encoding="utf-8") as f:
        json.dump(state, f)


class Event(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_replies = _load_auto_replies()
        self.replies_enabled = _load_replies_state()

    @commands.command(name="reload_replies")
    @commands.is_owner()
    async def reload_replies(self, ctx: commands.Context):
        """重新載入梗圖自動回應設定"""
        self.auto_replies = _load_auto_replies()
        await ctx.send(f"已重新載入 {len(self.auto_replies)} 組自動回應")

    @commands.command(name="autoreply")
    @commands.has_permissions(manage_guild=True)
    async def toggle_autoreply(self, ctx: commands.Context):
        """開關關鍵字自動回應（管理員限定）"""
        guild_id = str(ctx.guild.id)
        current = self.replies_enabled.get(guild_id, True)
        self.replies_enabled[guild_id] = not current
        _save_replies_state(self.replies_enabled)
        status = "開啟" if not current else "關閉"
        await ctx.send(f"關鍵字自動回應已**{status}**")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        separators = string.punctuation + string.digits + string.whitespace
        excluded = string.ascii_letters

        if message.author.id == self.bot.user.id:
            return

        try:
            with open(BADWORD_JSON, "r", encoding="utf-8") as file:
                words = json.load(file)
        except FileNotFoundError:
            logger.info("badword.json does not exist, creating")
            with open(BADWORD_JSON, "w", encoding="utf-8") as file:
                words = {"useless": [""]}
                json.dump(words, file)

        # Auto replies (respects per-guild toggle)
        guild_id = str(message.guild.id) if message.guild else None
        replies_on = self.replies_enabled.get(guild_id, True) if guild_id else True

        if replies_on:
            if "菜" in message.content:
                await message.reply(file=discord.File("ur_noob.png"))

            if "我只是" in message.content or "只有我" in message.content or "這我" in message.content:
                await message.add_reaction(lookup("REGIONAL INDICATOR SYMBOL LETTER M"))
                await message.add_reaction(lookup("REGIONAL INDICATOR SYMBOL LETTER E"))

            for entry in self.auto_replies:
                if not entry["urls"]:
                    continue
                for trigger in entry["triggers"]:
                    if trigger in message.content:
                        await message.channel.send(random.choice(entry["urls"]))
                        break

        # Bad word filter (always active, independent of autoreply toggle)
        if message.guild is None:
            return

        prefixes = await self.bot.get_prefix(message)
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        if any(p and message.content.startswith(p) for p in prefixes):
            return
        if guild_id not in words:
            return

        for word in words[guild_id]:
            formatted_word = f"[{re.escape(separators)}]*".join(list(word))
            regex_true = re.compile(fr"{formatted_word}", re.IGNORECASE)
            regex_false = re.compile(fr"([{re.escape(excluded)}]+{re.escape(word)})|({re.escape(word)}[{re.escape(excluded)}]+)", re.IGNORECASE)
            profane = False
            if (regex_true.search(message.content) is not None
                    and regex_false.search(message.content) is None) or word in message.content:
                profane = True
            if profane:
                await message.delete()
                await message.channel.send("哦?你說了不該說的話了喔!")


async def setup(bot):
    await bot.add_cog(Event(bot))
