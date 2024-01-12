# -*- coding: utf-8 -*-

import os
import sys

import discord


from discord.ext import commands



sys.path.append(os.path.abspath(".."))
from attend_program import *



class Attend(commands.Cog):
    def __init__(self,bot:commands.Bot):
        self.bot=bot



    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await ctx.send('An error occurred: {}'.format(str(error)))


    @commands.command(name='attend') 
    async def _attend(self, ctx: commands.Context, course_name: str = "None" , pwd: str= "None"):
        """點名"""
        if(course_name=="None" or pwd=="None"):
            await ctx.send("輸入錯誤，請重新輸入")
            return
        await ctx.send("點名中...")
        result=attend_main(course_name,pwd)
        await ctx.send(result)
        
    @commands.Cog.listener()
    async def on_message(self,message:discord.Message):
        if message.author.id != self.bot.user.id:
            if("https://ecourse2.ccu.edu.tw/mod/attendance/attendance.php?qrpass=" in message.content):
                await message.channel.send("點名中...")
                result=attend_with_link(message.content)
                await message.channel.send(result)


async def setup(bot):
    await bot.add_cog(Attend(bot))

    
    