# -*- coding: utf-8 -*-
import discord
from discord.ext import commands
import asyncio
import requests
import random
import datetime
from bs4 import BeautifulSoup
import re
import json
from pathlib import Path


prefix_json="json/prefix.json"
badword_json="json/badword.json"


class Other(commands.Cog):
    def __init__(self,bot:commands.Bot):
        self.bot=bot

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await ctx.send('An error occurred: {}'.format(str(error)))


    @commands.command(name='count') 
    async def _count(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        """語音頻道人數"""
        if(channel==None):
            await ctx.send("請輸入語音頻道")
            return
        sum=0
        for i in range(len(channel.members)):
            if(not channel.members[i].bot):
                sum+=1
        print(sum)
        await ctx.send('目前'+channel.name+'裡面有'+str(sum)+'人')

    @commands.command(name='unbanwords')
    # @commands.has_permissions(manage_guild=True)
    async def _unbanwords(self,ctx:commands.Context,word:str=None):
        """解ban特定的字"""
        if(word==None):
            await ctx.send("請輸入要解ban的單字")
            return
        with open(Path(badword_json),"rb") as f:
            words = json.load(f)
        f.close()
        if(str(ctx.guild.id) in words):
            for i in range(len(words[str(ctx.guild.id)])):
                if(words[str(ctx.guild.id)][i]==word):
                    words[str(ctx.guild.id)].remove(word)
                    if(len(words[str(ctx.guild.id)])==0):
                        del words[str(ctx.guild.id)]
                    await ctx.send("設定成功!")
                    with open(Path(badword_json),"w") as r:
                        json.dump(words,r)
                    r.close()
                    return
            await ctx.send("這個詞沒有被ban過喔!")    
            
        else:
            await ctx.send("沒有被ban的單字喔!")
            

    @commands.command(name='banwords')
    # @commands.has_permissions(manage_guild=True)
    async def _banwords(self,ctx:commands.Context,word=None):
        """ban特定的字"""
        if(word==None):
            await ctx.send("請輸入要ban的單字")
            return
        with open(Path(badword_json),"rb") as f:            #words : dictionary
            words = json.load(f)                            #word  : str
        f.close()                                           #a     : list
        
        
        print('----------------')
        print(word)
        print('----------------')
        if(str(ctx.guild.id) not in words):
            await ctx.send(word)
            a=word.split()
            await ctx.send(a)
            words.setdefault(str(ctx.guild.id),a)
            with open(Path(badword_json),"w") as r:
                json.dump(words,r)
            r.close()
            await ctx.send("設定成功!")
        else:
            for i in range(len(words[str(ctx.guild.id)])):
                if(words[str(ctx.guild.id)][i]==word):
                    await ctx.send("已經ban過了喔!")
                    return
            a=word.split()
            await ctx.send(a)
            for i in range(len(a)):
                words[str(ctx.guild.id)].append(a[i])
            with open(Path(badword_json),"w") as r:
                json.dump(words,r)
            r.close()
            await ctx.send("設定成功!")
            
            
    @commands.command(name='banwordlist')
    # @commands.has_permissions(manage_guild=True)
    async def _banwordlist(self,ctx:commands.Context):
        """banlist"""
        
        with open(Path(badword_json),"rb") as f:            #words : dictionary
            words = json.load(f)                            #word  : str
        f.close()                                           #a     : list
        
        if(str(ctx.guild.id) not in words):
            await ctx.send("目前還沒禁任何文字")
            return
        
        for i in range(len(words[str(ctx.guild.id)])):
            await ctx.send(words[str(ctx.guild.id)][i])

                       
        

    


    @commands.command(name='poll')
    async def poll(self,ctx:commands.Context,topic,c1,c2,c3):
        """投票(主題 選項一 選項二 持續時間)"""
        emb=discord.Embed(title=topic,description=f":one:{c1}\n\n:two:{c2}",timestamp=datetime.datetime.utcnow())
        emb.set_footer(text=f"由{ctx.author.name}發起投票")
        msg=await ctx.channel.send(embed=emb)
        await msg.add_reaction('1️⃣')
        await msg.add_reaction('2️⃣')
        c4=int(c3)
        await asyncio.sleep(c4)

        newmessage=await ctx.fetch_message(msg.id)
        onechoice=await newmessage.reactions[0].users().flatten()
        secchoice=await newmessage.reactions[1].users().flatten()

        result="平手"
        if len(onechoice)>len(secchoice):
            result=c1
        elif len(secchoice)>len(onechoice):
            result=c2
        emb=discord.Embed(title=topic,description=f"投票結果:{result}",timestamp=datetime.datetime.utcnow())
    
        await newmessage.edit(embed=emb)
        
        
        
    @commands.command(name='test')
    @commands.guild_only()
    async def test(self, ctx:commands.Context):
        """test"""
        channel=await self.bot.fetch_channel('1063016394058387466')
        await channel.create_thread(name="測試", message="test", auto_archive_duration=4320, type=None, reason=None)

    @commands.command(name='prefix')
    @commands.guild_only()
    async def setprefix(self, ctx, *, prefixes=""):
        """設定前綴"""
        
        if(prefixes==""):
            await ctx.send("please enter the prefix.")
            return


        with open(prefix_json,"rb") as f:
            custom_prefixes = json.load(f)
            custom_prefixes[ctx.guild.id] = prefixes
            dict=custom_prefixes
        f.close()
        with open(prefix_json,"w") as r:
            json.dump(dict,r)
        r.close()
        await ctx.send("Prefix was set to {} ".format(prefixes))

    @commands.command(name='draw')
    async def draw(self,ctx:commands.Context,number:int, channel: discord.VoiceChannel = None):
        """抽獎(要抽的數量 在哪個頻道抽)"""
        
        if(channel==None):
            await ctx.send("請輸入語音頻道")
            return
        sum=0
        li=[]
        for i in range(len(channel.members)):
            if(not channel.members[i].bot):
                sum+=1
                li.append(channel.members[i].name)
        print(sum)
        if(number>sum):
            del li
            await ctx.send("人數小於要抽的數目")
            return
        jackpot=[]
        i=0
        while(i<number):
            tmp=random.randint(0,sum-1)
            if(not channel.members[tmp].name in jackpot):
                jackpot.append(channel.members[tmp].name)
                i+=1
        await ctx.send("恭喜")
        for i in range(len(jackpot)):
            await ctx.send(channel.members[i].name)

async def setup(bot):
    await bot.add_cog(Other(bot))

    
    