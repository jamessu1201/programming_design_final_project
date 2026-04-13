# -*- coding: utf-8 -*-
import os
import logging

import discord
from discord.ext import commands
from discord.utils import get
import json
import yaml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

PREFIX_JSON = "json/prefix.json"
CONFIG_PATH = "config.yaml"
DEFAULT_PREFIX = "!"

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)

token = os.environ.get("bot_token")
if token is None:
    try:
        with open("api_key/token.txt", "r") as bot_token:
            token = bot_token.read().strip()
    except FileNotFoundError:
        logger.error("token does not exist, please create a bot")
        os._exit(0)

try:
    with open(PREFIX_JSON) as f:
        custom_prefixes = json.load(f)
except FileNotFoundError:
    logger.info("prefix.json does not exist, creating")
    with open(PREFIX_JSON, "w") as f:
        json.dump({}, f)


def main():
    async def determine_prefix(bot, message):
        guild = message.guild
        if guild:
            with open(PREFIX_JSON) as f:
                prefixes = json.load(f)
            return prefixes.get(str(guild.id), DEFAULT_PREFIX)
        return DEFAULT_PREFIX

    owners = []
    try:
        with open("private/owners.txt", "r") as r:
            raw = r.read()
            for owner in raw.split(","):
                owners.append(int(owner.strip()))
    except FileNotFoundError:
        logger.warning("private/owners.txt not found, no owners set")

    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.voice_states = True
    intents.reactions = True

    bot = commands.Bot(
        command_prefix=determine_prefix,
        owner_ids=set(owners),
        description="james and michael的萬能機器人",
        intents=intents,
    )
    bot.config = config

    @bot.event
    async def on_ready():
        for file in os.listdir("cogs"):
            if file.endswith(".py") and not file.startswith("_"):
                logger.info("Loading cogs.%s", file[:-3])
                await bot.load_extension(f"cogs.{file[:-3]}")
        logger.info("Logged in as: %s (%s)", bot.user.name, bot.user.id)

    @bot.event
    async def on_raw_reaction_add(payload):
        reaction_channel = config["channels"]["reaction_delete"]
        if payload.channel_id == reaction_channel:
            if payload.emoji.name == "⏭":
                channel = bot.get_channel(payload.channel_id)
                message = await channel.fetch_message(payload.message_id)
                reaction = get(message.reactions, emoji=payload.emoji.name)
                if reaction and reaction.count >= 2:
                    await message.delete()

    bot.run(token)


if __name__ == "__main__":
    main()
