# -*- coding: utf-8 -*-
"""屁眼點數：群組活躍度點數系統（只限特定伺服器）。

- 進語音每分鐘 +VOICE_POINTS_PER_MIN 點（排除 AFK 頻道 / 自己靜音或拒聽 / 頻道只剩一個真人）。
- 每發一則訊息 +MSG_POINTS 點（不限）。
- /points top 看排行榜、/points view 看自己或某人、/points reset 管理員歸零。
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

import discord
from discord import app_commands
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)

TARGET_GUILD = 960893399014211614
VOICE_POINTS_PER_MIN = 5
MSG_POINTS = 1
POINTS_JSON = "json/points.json"

LEADERBOARD_SIZE = 15
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


# ── 持久化（純函式，方便測試） ──

def _load() -> dict:
    try:
        with open(POINTS_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    os.makedirs(os.path.dirname(POINTS_JSON), exist_ok=True)
    with open(POINTS_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


# ── 點數核心邏輯（純函式，operate on passed dict） ──

def _award(data: dict, guild_id, member_id, name, *, points, messages=0, voice_min=0):
    """對某使用者累加點數與明細，回傳新的總點數。"""
    g = data.setdefault(str(guild_id), {})
    rec = g.get(str(member_id))
    if rec is None:
        rec = {"name": name, "points": 0, "messages": 0, "voice_min": 0}
        g[str(member_id)] = rec
    rec["name"] = name
    rec["points"] += points
    rec["messages"] += messages
    rec["voice_min"] += voice_min
    return rec["points"]


def _voice_channel_eligible(num_humans: int, is_afk: bool) -> bool:
    """頻道層級資格：至少兩個真人、且不是 AFK 頻道。"""
    return num_humans >= 2 and not is_afk


def _member_voice_eligible(self_mute: bool, self_deaf: bool) -> bool:
    """個人層級資格：沒有自己靜音或拒聽。"""
    return not (self_mute or self_deaf)


def _leaderboard(data: dict, guild_id):
    """回傳依點數由高到低排序的 [(user_id, record), ...]。"""
    g = data.get(str(guild_id), {})
    return sorted(g.items(), key=lambda kv: kv[1]["points"], reverse=True)


# ── Cog ──

class Points(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lock = asyncio.Lock()
        self.voice_tick.start()

    def cog_unload(self):
        if self.voice_tick.is_running():
            self.voice_tick.cancel()

    # --- 語音掃描 loop ---

    @tasks.loop(seconds=60)
    async def voice_tick(self):
        guild = self.bot.get_guild(TARGET_GUILD)
        if guild is None:
            return
        afk_id = guild.afk_channel.id if guild.afk_channel else None
        async with self._lock:
            data = _load()
            changed = False
            for vc in guild.voice_channels:
                humans = [m for m in vc.members if not m.bot]
                if not _voice_channel_eligible(len(humans), vc.id == afk_id):
                    continue
                for m in humans:
                    vs = m.voice
                    if vs and _member_voice_eligible(vs.self_mute, vs.self_deaf):
                        _award(data, guild.id, m.id, m.display_name,
                               points=VOICE_POINTS_PER_MIN, voice_min=1)
                        changed = True
            if changed:
                _save(data)

    @voice_tick.before_loop
    async def before_voice_tick(self):
        await self.bot.wait_until_ready()

    @voice_tick.error
    async def voice_tick_error(self, error):
        logger.error("voice_tick error: %s", error)

    # --- 訊息給點 ---

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild is None:
            return
        if message.guild.id != TARGET_GUILD:
            return
        async with self._lock:
            data = _load()
            _award(data, message.guild.id, message.author.id,
                   message.author.display_name, points=MSG_POINTS, messages=1)
            _save(data)

    # --- slash 指令 ---

    group = app_commands.Group(name="points", description="屁眼點數", guild_only=True)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        """擋掉非目標伺服器。回傳 True 表示可以繼續。"""
        if interaction.guild_id != TARGET_GUILD:
            await interaction.response.send_message(
                "此功能僅在特定伺服器啟用。", ephemeral=True)
            return False
        return True

    @group.command(name="top", description="看屁眼點數排行榜")
    async def top(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        board = _leaderboard(_load(), interaction.guild_id)
        if not board:
            return await interaction.response.send_message(
                "目前還沒有人有屁眼點數，快去語音或聊天吧。", ephemeral=True)

        lines = []
        for rank, (_uid, rec) in enumerate(board[:LEADERBOARD_SIZE], start=1):
            tag = MEDALS.get(rank, f"**{rank}.**")
            lines.append(
                f"{tag} {rec['name']} — **{rec['points']}** 點"
                f"（🎙️{rec['voice_min']} 分 / 💬{rec['messages']} 則）"
            )
        embed = discord.Embed(
            title="🍑 屁眼點數排行榜",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        total = len(board)
        if total > LEADERBOARD_SIZE:
            embed.set_footer(text=f"共 {total} 人上榜，只顯示前 {LEADERBOARD_SIZE} 名")
        await interaction.response.send_message(
            embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="view", description="看自己或某人的屁眼點數")
    @app_commands.describe(user="要查誰（不填就是自己）")
    async def view(self, interaction: discord.Interaction, user: discord.Member = None):
        if not await self._guard(interaction):
            return
        target = user or interaction.user
        board = _leaderboard(_load(), interaction.guild_id)
        rank = next((i for i, (uid, _) in enumerate(board, start=1)
                     if uid == str(target.id)), None)
        if rank is None:
            who = "你" if target == interaction.user else target.display_name
            return await interaction.response.send_message(
                f"{who}還沒有任何屁眼點數。", ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
        rec = board[rank - 1][1]
        embed = discord.Embed(
            title=f"🍑 {rec['name']} 的屁眼點數",
            description=(
                f"**{rec['points']}** 點 · 第 **{rank}** 名（共 {len(board)} 人）\n"
                f"🎙️ 語音 {rec['voice_min']} 分鐘 ・ 💬 訊息 {rec['messages']} 則"
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(
            embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="reset", description="歸零某人的點數；不填 user 則清空整個伺服器（限管理員）")
    @app_commands.describe(user="要歸零的人（不填＝清空整個伺服器）")
    async def reset(self, interaction: discord.Interaction, user: discord.Member = None):
        if not await self._guard(interaction):
            return
        is_owner = await self.bot.is_owner(interaction.user)
        perms = getattr(interaction.user, "guild_permissions", None)
        if not is_owner and not (perms and perms.manage_guild):
            return await interaction.response.send_message(
                "只有管理員（管理伺服器權限）或 bot owner 能歸零點數。", ephemeral=True)

        async with self._lock:
            data = _load()
            g = data.get(str(interaction.guild_id), {})
            if user is None:
                count = len(g)
                data.pop(str(interaction.guild_id), None)
                _save(data)
                msg = f"🧹 已清空整個伺服器的屁眼點數（{count} 人歸零）。"
            else:
                if str(user.id) in g:
                    del g[str(user.id)]
                    if not g:
                        data.pop(str(interaction.guild_id), None)
                    _save(data)
                    msg = f"🧹 已把 {user.display_name} 的屁眼點數歸零。"
                else:
                    msg = f"{user.display_name} 本來就沒有點數。"
        await interaction.response.send_message(
            msg, allowed_mentions=discord.AllowedMentions.none())

    # --- 統一錯誤處理 ---

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        logger.error("points command error: %s", error)
        msg = f"發生錯誤：{error}"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Points(bot))
