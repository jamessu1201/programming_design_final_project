# -*- coding: utf-8 -*-
import logging
import discord
from discord import app_commands
from discord.ext import commands
import random
import json
from pathlib import Path

logger = logging.getLogger(__name__)

PREFIX_JSON = "json/prefix.json"
BADWORD_JSON = "json/badword.json"


class PollView(discord.ui.View):
    def __init__(
        self,
        question: str,
        options: list,
        *,
        creator_id: int,
        multiple: bool,
        change_vote: bool,
        duration_seconds: int,
    ):
        super().__init__(timeout=duration_seconds)
        self.question = question
        self.options = options
        self.creator_id = creator_id
        self.multiple = multiple
        self.change_vote = change_vote
        self.votes: dict = {}  # user_id -> set of option indices
        self.ended = False
        self.message = None

        for i, opt in enumerate(options):
            btn = discord.ui.Button(
                label=opt[:80],
                style=discord.ButtonStyle.primary,
                row=i // 5,
            )
            btn.callback = self._make_vote_callback(i)
            self.add_item(btn)

        end_row = ((len(options) - 1) // 5) + 1
        end_btn = discord.ui.Button(
            label="結束投票",
            style=discord.ButtonStyle.danger,
            emoji="🛑",
            row=min(end_row, 4),
        )
        end_btn.callback = self._end_callback
        self.add_item(end_btn)

    def _make_vote_callback(self, idx: int):
        async def cb(interaction: discord.Interaction):
            if self.ended:
                return await interaction.response.send_message(
                    "投票已結束", ephemeral=True
                )
            uid = interaction.user.id
            current = self.votes.setdefault(uid, set())

            if idx in current:
                if not self.change_vote:
                    return await interaction.response.send_message(
                        "這個投票不允許更改選擇", ephemeral=True
                    )
                current.discard(idx)
                action = f"已取消投給「{self.options[idx]}」"
            elif self.multiple:
                current.add(idx)
                action = f"已加投「{self.options[idx]}」"
            else:
                if current and not self.change_vote:
                    return await interaction.response.send_message(
                        "這個投票不允許更改選擇", ephemeral=True
                    )
                current.clear()
                current.add(idx)
                action = f"已投給「{self.options[idx]}」"

            if not current:
                del self.votes[uid]

            await interaction.response.edit_message(
                embed=self._build_embed(), view=self
            )
            await interaction.followup.send(action, ephemeral=True)

        return cb

    async def _end_callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.creator_id:
            return await interaction.response.send_message(
                "只有發起人可以結束投票", ephemeral=True
            )
        self.ended = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            embed=self._build_embed(), view=self
        )
        self.stop()

    def _tally(self):
        counts = [0] * len(self.options)
        for s in self.votes.values():
            for i in s:
                counts[i] += 1
        return counts

    def _build_embed(self) -> discord.Embed:
        counts = self._tally()
        voters = len(self.votes)
        total_votes = sum(counts)
        denom = total_votes if self.multiple else voters
        lines = []
        for opt, c in zip(self.options, counts):
            pct = (c / denom * 100) if denom else 0
            filled = int(round(pct / 10))
            bar = "█" * filled + "░" * (10 - filled)
            lines.append(f"**{opt}**\n`{bar}` {c} 票 ({pct:.0f}%)")

        title = ("🔒 " if self.ended else "📊 ") + self.question
        desc = "\n\n".join(lines)
        footer = f"投票人數 **{voters}**"
        if self.multiple and total_votes != voters:
            footer += f" · 總票數 **{total_votes}**"
        footer += f" · {'允許改投' if self.change_vote else '不可改投'}"
        if self.multiple:
            footer += " · 可多選"
        if self.ended:
            footer += " · 已結束"
        desc += "\n\n━━━━━━\n" + footer

        return discord.Embed(
            title=title,
            description=desc,
            color=discord.Color.dark_grey() if self.ended else discord.Color.blurple(),
        )

    async def on_timeout(self):
        self.ended = True
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(embed=self._build_embed(), view=self)
            except discord.HTTPException:
                pass


class Other(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        await ctx.send("An error occurred: {}".format(str(error)))

    @commands.command(name="count")
    async def _count(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        """語音頻道人數"""
        if channel is None:
            await ctx.send("請輸入語音頻道")
            return
        count = sum(1 for m in channel.members if not m.bot)
        await ctx.send(f"目前{channel.name}裡面有{count}人")

    @commands.command(name="unbanwords")
    # @commands.has_permissions(manage_guild=True)
    async def _unbanwords(self, ctx: commands.Context, word: str = None):
        """解ban特定的字"""
        if word is None:
            await ctx.send("請輸入要解ban的單字")
            return
        with open(Path(BADWORD_JSON), "r", encoding="utf-8") as f:
            words = json.load(f)
        guild_id = str(ctx.guild.id)
        if guild_id in words:
            if word in words[guild_id]:
                words[guild_id].remove(word)
                if len(words[guild_id]) == 0:
                    del words[guild_id]
                with open(Path(BADWORD_JSON), "w", encoding="utf-8") as r:
                    json.dump(words, r)
                await ctx.send("設定成功!")
                return
            await ctx.send("這個詞沒有被ban過喔!")
        else:
            await ctx.send("沒有被ban的單字喔!")

    @commands.command(name="banwords")
    # @commands.has_permissions(manage_guild=True)
    async def _banwords(self, ctx: commands.Context, word=None):
        """ban特定的字"""
        if word is None:
            await ctx.send("請輸入要ban的單字")
            return
        with open(Path(BADWORD_JSON), "r", encoding="utf-8") as f:
            words = json.load(f)
        guild_id = str(ctx.guild.id)
        if guild_id not in words:
            words[guild_id] = word.split()
            with open(Path(BADWORD_JSON), "w", encoding="utf-8") as r:
                json.dump(words, r)
            await ctx.send("設定成功!")
        else:
            for w in words[guild_id]:
                if w == word:
                    await ctx.send("已經ban過了喔!")
                    return
            words[guild_id].extend(word.split())
            with open(Path(BADWORD_JSON), "w", encoding="utf-8") as r:
                json.dump(words, r)
            await ctx.send("設定成功!")

    @commands.command(name="banwordlist")
    # @commands.has_permissions(manage_guild=True)
    async def _banwordlist(self, ctx: commands.Context):
        """banlist"""
        with open(Path(BADWORD_JSON), "r", encoding="utf-8") as f:
            words = json.load(f)
        guild_id = str(ctx.guild.id)
        if guild_id not in words:
            await ctx.send("目前還沒禁任何文字")
            return
        for w in words[guild_id]:
            await ctx.send(w)

    @commands.command(name="test")
    @commands.guild_only()
    async def test(self, ctx: commands.Context):
        """test"""
        cfg = self.bot.config
        channel = await self.bot.fetch_channel(cfg["channels"]["leetcode"])
        await channel.create_thread(
            name="測試", auto_archive_duration=4320,
            type=discord.ChannelType.public_thread,
        )

    @commands.hybrid_command(name="poll")
    @commands.guild_only()
    @app_commands.describe(
        question="問題（要投什麼票？）",
        option1="選項 1",
        option2="選項 2",
        option3="選項 3（選填）",
        option4="選項 4（選填）",
        option5="選項 5（選填）",
        option6="選項 6（選填）",
        option7="選項 7（選填）",
        option8="選項 8（選填）",
        option9="選項 9（選填）",
        option10="選項 10（選填）",
        hours="持續時間（小時，1–720，預設 24）",
        multiple="能不能多選（預設否）",
        change_vote="能不能改投（預設可以）",
    )
    async def poll(
        self,
        ctx: commands.Context,
        question: str,
        option1: str,
        option2: str,
        option3: str = None,
        option4: str = None,
        option5: str = None,
        option6: str = None,
        option7: str = None,
        option8: str = None,
        option9: str = None,
        option10: str = None,
        hours: int = 24,
        multiple: bool = False,
        change_vote: bool = True,
    ):
        """發起投票（用 /poll 會有欄位提示）

        按按鈕即可投票。發起人可以隨時按「結束投票」結算。
        """
        options = [
            o for o in (
                option1, option2, option3, option4, option5,
                option6, option7, option8, option9, option10,
            ) if o
        ]

        async def reply(msg):
            await ctx.send(msg, ephemeral=True)

        if len(question) > 256:
            return await reply("問題最長 256 字。")
        if not 1 <= hours <= 720:
            return await reply("持續時間必須介於 1–720 小時。")
        for opt in options:
            if len(opt) > 80:
                return await reply(f"選項「{opt}」超過 80 字上限。")

        view = PollView(
            question=question,
            options=options,
            creator_id=ctx.author.id,
            multiple=multiple,
            change_vote=change_vote,
            duration_seconds=hours * 3600,
        )
        embed = view._build_embed()

        try:
            if ctx.interaction is not None:
                await ctx.interaction.response.defer(ephemeral=True)
                msg = await ctx.channel.send(embed=embed, view=view)
                view.message = msg
                await ctx.interaction.followup.send("✅ 投票已建立", ephemeral=True)
            else:
                msg = await ctx.send(embed=embed, view=view)
                view.message = msg
        except discord.HTTPException as e:
            logger.error("Poll send failed: %s", e)
            await reply(f"發送投票失敗：{e}")

    @commands.command(name="prefix")
    @commands.guild_only()
    async def setprefix(self, ctx, *, prefixes=""):
        """設定前綴"""
        if prefixes == "":
            await ctx.send("please enter the prefix.")
            return
        with open(PREFIX_JSON, "r", encoding="utf-8") as f:
            custom_prefixes = json.load(f)
        custom_prefixes[str(ctx.guild.id)] = prefixes
        with open(PREFIX_JSON, "w", encoding="utf-8") as r:
            json.dump(custom_prefixes, r)
        await ctx.send("Prefix was set to {} ".format(prefixes))

    @commands.command(name="draw")
    async def draw(self, ctx: commands.Context, number: int, channel: discord.VoiceChannel = None):
        """抽獎(要抽的數量 在哪個頻道抽)"""
        if channel is None:
            await ctx.send("請輸入語音頻道")
            return
        non_bot_members = [m for m in channel.members if not m.bot]
        if number > len(non_bot_members):
            await ctx.send("人數小於要抽的數目")
            return
        winners = random.sample(non_bot_members, number)
        await ctx.send("恭喜")
        for winner in winners:
            await ctx.send(winner.name)


async def setup(bot):
    await bot.add_cog(Other(bot))
