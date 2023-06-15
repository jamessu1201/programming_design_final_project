# -*- coding: utf-8 -*-
import os
import discord
from discord.ext.commands.core import command
from async_timeout import timeout
from discord.ext import commands
import json
from discord.ext.commands.core import has_guild_permissions
from discord.utils import get


prefix_json="json/prefix.json"    #prefix.json path


default_prefixes = "!"            #if prefix does not set,then use default




try:                              #if token doesn't exist then return
    token=os.environ.get('bot_token')
    print(token)
except:
    print("token does not exist,please create a bot")
    os._exit(0)

try:                              #if file not exist then create
    with open(prefix_json) as f:
        print("prefix.json exists")
        custom_prefixes = json.load(f)
    f.close()
except:
    with open(prefix_json,"w+") as f:
        print("prefix.json does not exist,so created")
        prefix = {"useless":""}
        json.dump(prefix,f)
    f.close()


def main():
    async def determine_prefix(bot, message):
        guild = message.guild
        #Only allow custom prefixs in guild
        if guild:
            with open(prefix_json) as f:
                custom_prefixes = json.load(f)
            f.close()
            print(custom_prefixes.get(str(guild.id), default_prefixes))
            print(custom_prefixes)
            return custom_prefixes.get(str(guild.id), default_prefixes)
        else:
            return default_prefixes
    owners=[]
    try:
        with open("owners.txt","r") as r:
            raw=r.read()
            for owner in raw.split(","):
                owners.append(int(owner))
        r.close()
        print(owners)
    except:
        pass
    bot = commands.Bot(command_prefix=determine_prefix,owner_ids=set(owners), description='james and michael的萬能機器人',intents=discord.Intents.all())
    
    
    
    @bot.event
    async def on_ready():
        intents = discord.Intents().default()
        intents.message_content = True
        for file in os.listdir("cogs"):
            if(file.endswith(".py") and not file.startswith("_")):
                print(f"cogs.{file[:-3]}")
                await bot.load_extension(f"cogs.{file[:-3]}")
        print('Logged in as:\n{0.user.name}\n{0.user.id}'.format(bot))
    
    @bot.event
    async def on_raw_reaction_add(payload):
        if payload.channel_id == 980486619368935464:
            if payload.emoji.name == "⏭":
                channel = bot.get_channel(payload.channel_id)
                message = await channel.fetch_message(payload.message_id)
                reaction = get(message.reactions, emoji=payload.emoji.name)
                if reaction and reaction.count >=2:
                    await message.delete()

    bot.run(token)
    

if(__name__=='__main__'):         
    main()
    