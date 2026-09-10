# -*- coding: utf-8 -*-
import json
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

        txt_path = os.path.join(guild_dir, f"{channel_name}.txt")
        jsonl_path = os.path.join(guild_dir, f"{channel_name}.jsonl")

        local_dt = message.created_at.astimezone(
            datetime.timezone(datetime.timedelta(hours=8))
        )
        timestamp = local_dt.strftime("%Y-%m-%d %H:%M:%S")

        author = message.author
        username = author.name
        display_name = author.display_name
        attachment_urls = [a.url for a in message.attachments]

        line = f"[{timestamp}] @{username} ({display_name}): {message.content}"
        if attachment_urls:
            line += f" [附件: {', '.join(attachment_urls)}]"

        with open(txt_path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

        record = {
            "ts": local_dt.isoformat(),
            "guild_id": str(message.guild.id),
            "guild_name": message.guild.name,
            "channel_id": str(message.channel.id),
            "channel_name": message.channel.name,
            "message_id": str(message.id),
            "user_id": str(author.id),
            "username": username,
            "display_name": display_name,
            "content": message.content,
            "attachments": attachment_urls,
        }
        with open(jsonl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


async def setup(bot):
    await bot.add_cog(ChatLog(bot))
