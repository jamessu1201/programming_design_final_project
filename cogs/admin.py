# -*- coding: utf-8 -*-
import discord
from discord.ext import commands


class Admin(commands.Cog):
    """Admin-only commands that make the bot dynamic."""

    def __init__(self, bot):
        self.bot = bot

    @commands.command(hidden=True)
    @commands.is_owner()
    async def load(self,ctx:commands.Context, module : str =None):
        """Loads a module."""
        if(module==None):
            await ctx.send("please enter a module.")
            return
        print(module)
        try:
            await self.bot.load_extension(f"cogs.{module}")
        except Exception as e:
            await ctx.send('\N{PISTOL}')
            await ctx.send('{}: {}'.format(type(e).__name__, e))
        else:
            await ctx.send('\N{OK HAND SIGN}')

    @commands.command(hidden=True)
    @commands.is_owner()
    async def unload(self,ctx:commands.Context, module : str =None):
        """Unloads a module."""
        if(module==None):
            await ctx.send("please enter a module.")
            return
        print(module)
        try:
            await self.bot.unload_extension(f"cogs.{module}")
        except Exception as e:
            await ctx.send('\N{PISTOL}')
            await ctx.send('{}: {}'.format(type(e).__name__, e))
        else:
            await ctx.send('\N{OK HAND SIGN}')

    @commands.command(name='reload', hidden=True)
    @commands.is_owner()
    async def _reload(self,ctx:commands.Context, module : str =None):
        """Reloads a module."""
        if(module==None):
            await ctx.send("please enter a module.")
            return
        print(module)
        try:
            await self.bot.reload_extension(f"cogs.{module}")
        except Exception as e:

            await ctx.send('\N{PISTOL}')
            await ctx.send('{}: {}'.format(type(e).__name__, e))
        else:
            print('ok')
            await ctx.send('\N{OK HAND SIGN}')
    
    @commands.command(name='botstop', aliases=['bstop','shutdown','bye'],hidden=True)
    @commands.is_owner()
    async def botstop(self,ctx):
        print('Goodbye')
        await ctx.send('Goodbye')
        await self.bot.close()
        return


async def setup(bot):
    await bot.add_cog(Admin(bot))