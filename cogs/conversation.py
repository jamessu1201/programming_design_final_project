# -*- coding: utf-8 -*-
import re
import string
import discord
from discord.ext import commands
import random
import json
import utils
import time


class Conversation(commands.Cog):
    
    
    @commands.is_owner()
    @commands.command(name='sendtext')
    async def _sendtext(self,ctx:commands.Context,channel_id:int,*,message='-1'):
        
        channel = await ctx.bot.fetch_channel(channel_id)
        await channel.send(message)
        
            
    @commands.is_owner()
    @commands.command(name='sendreply')
    async def _sendreply(self,ctx:commands.Context,channel_id:int,message_id:int,message:str):
        
        channel = await ctx.bot.fetch_channel(channel_id)
        msg=await channel.fetch_message(message_id)            
        await msg.reply(message)

    @commands.is_owner()
    @commands.command(name='sendprivate')
    async def _sendprivate(self,ctx:commands.Context,user_id:int,message:str):
        
        user = await ctx.bot.fetch_user(user_id)

        await user.send(message)
        
    
            
            


async def setup(bot):
    await bot.add_cog(Conversation(bot))