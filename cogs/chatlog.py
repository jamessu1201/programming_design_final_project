# -*- coding: utf-8 -*-
import logging
import os
import re
import datetime

import discord
from discord.ext import commands

logger = logging.getLogger(__name__)

LOGS_DIR = "logs"


def _safe_name(name: str) -> str:
    """Remove characters that are invalid in file/folder names."""
    return re.sub(r'[<>:"/\\|?*]', '_', name)


class ChatLog(commands.Cog):

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.guild is None:
            return

        guild_name = _safe_name(f"{message.guild.name}_{message.guild.id}")
        channel_name = _safe_name(message.channel.name)

        guild_dir = os.path.join(LOGS_DIR, guild_name)
        os.makedirs(guild_dir, exist_ok=True)

        log_path = os.path.join(guild_dir, f"{channel_name}.txt")
        timestamp = message.created_at.astimezone(
            datetime.timezone(datetime.timedelta(hours=8))
        ).strftime("%Y-%m-%d %H:%M:%S")

        line = f"[{timestamp}] {message.author.display_name}: {message.content}"
        if message.attachments:
            urls = ", ".join(a.url for a in message.attachments)
            line += f" [附件: {urls}]"

        with open(log_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


async def setup(bot):
    await bot.add_cog(ChatLog(bot))
