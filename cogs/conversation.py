# -*- coding: utf-8 -*-
import discord
from discord.ext import commands


class Conversation(commands.Cog):

    @commands.is_owner()
    @commands.command(name="sendtext", hidden=True)
    async def _sendtext(self, ctx: commands.Context, channel_id: int, *, message="-1"):
        """以機器人身份在指定頻道發送訊息"""
        channel = await ctx.bot.fetch_channel(channel_id)
        await channel.send(message)

    @commands.is_owner()
    @commands.command(name="sendreply", hidden=True)
    async def _sendreply(self, ctx: commands.Context, channel_id: int, message_id: int, message: str):
        """以機器人身份回覆指定訊息"""
        channel = await ctx.bot.fetch_channel(channel_id)
        msg = await channel.fetch_message(message_id)
        await msg.reply(message)

    @commands.is_owner()
    @commands.command(name="sendprivate", hidden=True)
    async def _sendprivate(self, ctx: commands.Context, user_id: int, message: str):
        """以機器人身份私訊指定使用者"""
        user = await ctx.bot.fetch_user(user_id)
        await user.send(message)


async def setup(bot):
    await bot.add_cog(Conversation(bot))
