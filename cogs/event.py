# -*- coding: utf-8 -*-
import os
import re
import string
import logging
import random

import discord
from discord.ext import commands
from unicodedata import lookup

import storage

logger = logging.getLogger(__name__)

BADWORD_JSON = "json/badword.json"
# 可選的本機圖片；不在 git 裡（*.png 被 ignore）。沒有就跳過這個梗，不要讓
# on_message 中途拋例外——那會連帶讓同一則訊息的禁字過濾整個不執行。
NOOB_IMAGE = "ur_noob.png"
AUTO_REPLIES_JSON = "json/auto_replies.json"
REPLIES_STATE_JSON = "json/replies_state.json"


def _load_auto_replies():
    return storage.read_json(AUTO_REPLIES_JSON, default=[])


def _load_replies_state():
    """Load per-guild on/off state. Returns dict like {"guild_id": true/false}"""
    return storage.read_json(REPLIES_STATE_JSON)


def _save_replies_state(state):
    storage.write_json_atomic(REPLIES_STATE_JSON, state)


class Event(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_replies = _load_auto_replies()
        self.replies_enabled = _load_replies_state()

    async def reload_replies_now(self):
        """Re-read auto_replies + replies_state from disk. Callable from dashboard."""
        self.auto_replies = _load_auto_replies()
        self.replies_enabled = _load_replies_state()
        return len(self.auto_replies)

    @commands.command(name="reload_replies")
    @commands.is_owner()
    async def reload_replies(self, ctx: commands.Context):
        """重新載入梗圖自動回應設定"""
        n = await self.reload_replies_now()
        await ctx.send(f"已重新載入 {n} 組自動回應")

    @commands.command(name="autoreply")
    @commands.has_permissions(manage_guild=True)
    async def toggle_autoreply(self, ctx: commands.Context):
        """開關關鍵字自動回應（管理員限定）"""
        guild_id = str(ctx.guild.id)
        async with storage.lock_for(REPLIES_STATE_JSON):
            state = _load_replies_state()
            current = state.get(guild_id, True)
            state[guild_id] = not current
            _save_replies_state(state)
        self.replies_enabled = state
        status = "開啟" if not current else "關閉"
        await ctx.send(f"關鍵字自動回應已**{status}**")

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        separators = string.punctuation + string.digits + string.whitespace
        excluded = string.ascii_letters

        if message.author.id == self.bot.user.id:
            return

        words = storage.read_json(BADWORD_JSON)
        if not words:
            words = {"useless": [""]}

        # Auto replies (respects per-guild toggle)
        guild_id = str(message.guild.id) if message.guild else None
        replies_on = self.replies_enabled.get(guild_id, True) if guild_id else True

        if replies_on:
            if "菜" in message.content and os.path.isfile(NOOB_IMAGE):
                await message.reply(file=discord.File(NOOB_IMAGE))

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
            # 每個字元都要 escape：禁字若含 ( ) 等 regex 元字元，未 escape 會讓
            # re.compile 拋 re.error，連帶讓這個伺服器的自動回應與過濾全部停擺。
            formatted_word = f"[{re.escape(separators)}]*".join(re.escape(c) for c in word)
            try:
                regex_true = re.compile(formatted_word, re.IGNORECASE)
            except re.error:
                logger.warning("禁字 %r 無法編譯成 regex，已略過", word)
                continue
            regex_false = re.compile(
                fr"([{re.escape(excluded)}]+{re.escape(word)})|({re.escape(word)}[{re.escape(excluded)}]+)",
                re.IGNORECASE)
            profane = False
            if (regex_true.search(message.content) is not None
                    and regex_false.search(message.content) is None) or word in message.content:
                profane = True
            if profane:
                await message.delete()
                await message.channel.send("哦?你說了不該說的話了喔!")


async def setup(bot):
    await bot.add_cog(Event(bot))
