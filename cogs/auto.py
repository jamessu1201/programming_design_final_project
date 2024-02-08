# -*- coding: utf-8 -*-
import re
import string
import discord
from discord.ext import commands,tasks
import random
import json
import utils
import time
import datetime





from twocaptcha import TwoCaptcha

import platform

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By

from selenium.webdriver.support.ui import WebDriverWait,Select
from selenium.webdriver.support import expected_conditions as EC


import os
import sys
sys.path.append(os.path.abspath(".."))
from leetcode import *




utc = datetime.timezone.utc

happy_birthday_time = datetime.time(hour=0, minute=0, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))

question_time = datetime.time(hour=8, minute=10, tzinfo=datetime.timezone(datetime.timedelta(hours=8)))

curr_dt = datetime.datetime.now()

print(happy_birthday_time)
print("Current datetime: ", curr_dt)

class Auto(commands.Cog):
    
    def __init__(self,bot:commands.Bot):
        self.bot=bot
        self.happy_birthday.start()
        self.leetcode.start()

    @tasks.loop(time=happy_birthday_time)
    async def happy_birthday(self):
        channel = await self.bot.fetch_channel('1056547645499379753')
        await channel.send('<@&1104820254145790133>')
        await channel.send('<@&1148518925496225803>')
        await channel.send('<@&1151170809457541282>')
        await channel.send('<@&1153019088252186734>')
        await channel.send('<@&1065064029527224341> 生日快樂🎉')
        await channel.send('https://giphy.com/gifs/xTcnSSsbe4hhZBvV6M')
        
        
    @tasks.loop(time=question_time)
    async def leetcode(self):
        channel=await self.bot.fetch_channel('1063016394058387466')
        thread=await channel.create_thread(name=main(), message=None, auto_archive_duration=4320, type=discord.ChannelType.public_thread, reason=None)
        await thread.send(get_link())
        
        
    # async def check_attend(self):
        
        
        

        
    

        


async def setup(bot):
    await bot.add_cog(Auto(bot))