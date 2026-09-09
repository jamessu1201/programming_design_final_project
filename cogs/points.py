# -*- coding: utf-8 -*-
"""活躍度點數系統。名稱、費率與適用伺服器都在 config.yaml 的 `points:` 區塊。

- 進語音每分鐘 +voice_points_per_min 點（排除 AFK 頻道 / 自己靜音或拒聽 / 頻道只剩一個真人）。
- 每發一則訊息 +message_points 點（不限）。
- /points top 看排行榜、/points view 看自己或某人、/points reset 管理員歸零。
"""
from __future__ import annotations

import logging

import discord
import yaml
from discord import app_commands
from discord.ext import commands, tasks

import storage

logger = logging.getLogger(__name__)

CONFIG_PATH = "config.yaml"
POINTS_JSON = "json/points.json"

DEFAULTS = {
    "guild_id": None,        # None = 所有伺服器都啟用
    "display_name": "活躍點數",
    "emoji": "⭐",
    "voice_points_per_min": 1,
    "message_points": 1,
}

LEADERBOARD_SIZE = 15
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


# ── 設定 ──

def points_config(bot) -> dict:
    """執行期設定。bot.config 是權威來源（!deploy 會重載它），缺的補預設。"""
    cfg = dict(DEFAULTS)
    cfg.update((getattr(bot, "config", None) or {}).get("points") or {})
    return cfg


def points_enabled(bot, guild_id) -> bool:
    """guild_id 設 null（None）代表不限伺服器。"""
    target = points_config(bot)["guild_id"]
    return target is None or guild_id == target


def _config_from_file() -> dict:
    """slash 指令的 description 在 import 時就定案，那時還碰不到 bot.config，
    所以顯示用的名稱/emoji 直接讀一次 config.yaml。改了要 !reload points，
    指令描述還要再 !sync 才會更新。"""
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return (yaml.safe_load(f) or {}).get("points") or {}
    except Exception:
        return {}


_DISPLAY = {**DEFAULTS, **_config_from_file()}
POINTS_NAME = _DISPLAY["display_name"]
POINTS_EMOJI = _DISPLAY["emoji"]


# ── 持久化（純函式，方便測試） ──

def _load() -> dict:
    return storage.read_json(POINTS_JSON)


def _save(data: dict) -> None:
    storage.write_json_atomic(POINTS_JSON, data)


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


# ── 排行榜分頁器 ──

class LeaderboardView(discord.ui.View):
    """排行榜的 ◀▶ 翻頁（模仿 others.py 的 PollView）。只有下指令的人能翻。"""

    PER_PAGE = LEADERBOARD_SIZE

    def __init__(self, board, invoker_id: int):
        super().__init__(timeout=120)
        self.board = board
        self.invoker_id = invoker_id
        self.page = 0
        self.total_pages = max(1, (len(board) + self.PER_PAGE - 1) // self.PER_PAGE)
        self.message = None
        self._sync_buttons()

    def _sync_buttons(self):
        self.prev_page.disabled = self.page <= 0
        self.next_page.disabled = self.page >= self.total_pages - 1

    def _build_embed(self) -> discord.Embed:
        start = self.page * self.PER_PAGE
        lines = []
        for rank, (uid, rec) in enumerate(self.board[start:start + self.PER_PAGE], start=start + 1):
            tag = MEDALS.get(rank, f"**{rank}.**")
            lines.append(
                f"{tag} <@{uid}> — **{rec['points']}** 點"
                f"（🎙️{rec['voice_min']} 分 / 💬{rec['messages']} 則）"
            )
        embed = discord.Embed(
            title=f"{POINTS_EMOJI} {POINTS_NAME}排行榜",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"第 {self.page + 1}/{self.total_pages} 頁 · 共 {len(self.board)} 人")
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.invoker_id:
            await interaction.response.send_message(
                "只有使用指令的人可以翻頁，你可以自己用 `/points top`。", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="◀", style=discord.ButtonStyle.secondary)
    async def prev_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    @discord.ui.button(emoji="▶", style=discord.ButtonStyle.secondary)
    async def next_page(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.total_pages - 1, self.page + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


# ── Cog ──

class Points(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Shared with the dashboard's points route so bot writes and dashboard
        # resets serialise against each other (same process, same loop).
        self._lock = storage.lock_for(POINTS_JSON)
        self.voice_tick.start()

    def cog_unload(self):
        if self.voice_tick.is_running():
            self.voice_tick.cancel()

    # --- 語音掃描 loop ---

    @tasks.loop(seconds=60)
    async def voice_tick(self):
        cfg = points_config(self.bot)
        target = cfg["guild_id"]
        if target is None:
            guilds = list(self.bot.guilds)
        else:
            guild = self.bot.get_guild(target)
            guilds = [guild] if guild else []
        if not guilds:
            return
        async with self._lock:
            data = _load()
            changed = False
            for guild in guilds:
                afk_id = guild.afk_channel.id if guild.afk_channel else None
                for vc in guild.voice_channels:
                    humans = [m for m in vc.members if not m.bot]
                    if not _voice_channel_eligible(len(humans), vc.id == afk_id):
                        continue
                    for m in humans:
                        vs = m.voice
                        if vs and _member_voice_eligible(vs.self_mute, vs.self_deaf):
                            _award(data, guild.id, m.id, m.display_name,
                                   points=cfg["voice_points_per_min"], voice_min=1)
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
        if not points_enabled(self.bot, message.guild.id):
            return
        cfg = points_config(self.bot)
        async with self._lock:
            data = _load()
            _award(data, message.guild.id, message.author.id,
                   message.author.display_name,
                   points=cfg["message_points"], messages=1)
            _save(data)

    # --- slash 指令 ---

    group = app_commands.Group(name="points", description=POINTS_NAME, guild_only=True)

    async def _guard(self, interaction: discord.Interaction) -> bool:
        """擋掉非目標伺服器。回傳 True 表示可以繼續。"""
        if not points_enabled(self.bot, interaction.guild_id):
            await interaction.response.send_message(
                "此功能未在這個伺服器啟用。", ephemeral=True)
            return False
        return True

    @group.command(name="top", description=f"看{POINTS_NAME}排行榜")
    async def top(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        board = _leaderboard(_load(), interaction.guild_id)
        if not board:
            return await interaction.response.send_message(
                f"目前還沒有人有{POINTS_NAME}，快去語音或聊天吧。", ephemeral=True)

        view = LeaderboardView(board, interaction.user.id)
        embed = view._build_embed()
        if view.total_pages == 1:
            return await interaction.response.send_message(
                embed=embed, allowed_mentions=discord.AllowedMentions.none())
        await interaction.response.send_message(
            embed=embed, view=view, allowed_mentions=discord.AllowedMentions.none())
        view.message = await interaction.original_response()

    @group.command(name="view", description=f"看自己或某人的{POINTS_NAME}")
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
                f"{who}還沒有任何{POINTS_NAME}。", ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none())
        rec = board[rank - 1][1]
        embed = discord.Embed(
            title=f"{POINTS_EMOJI} {POINTS_NAME}",
            description=(
                f"{target.mention}\n"
                f"**{rec['points']}** 點 · 第 **{rank}** 名（共 {len(board)} 人）\n"
                f"🎙️ 語音 {rec['voice_min']} 分鐘 ・ 💬 訊息 {rec['messages']} 則"
            ),
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(
            embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @group.command(name="reset", description="歸零某人的點數；不填 user 則清空整個伺服器（限 bot owner）")
    @app_commands.describe(user="要歸零的人（不填＝清空整個伺服器）")
    async def reset(self, interaction: discord.Interaction, user: discord.Member = None):
        if not await self._guard(interaction):
            return
        if not await self.bot.is_owner(interaction.user):
            return await interaction.response.send_message(
                "只有 bot owner 能歸零點數。", ephemeral=True)

        async with self._lock:
            data = _load()
            g = data.get(str(interaction.guild_id), {})
            if user is None:
                count = len(g)
                data.pop(str(interaction.guild_id), None)
                _save(data)
                msg = f"🧹 已清空整個伺服器的{POINTS_NAME}（{count} 人歸零）。"
            else:
                if str(user.id) in g:
                    del g[str(user.id)]
                    if not g:
                        data.pop(str(interaction.guild_id), None)
                    _save(data)
                    msg = f"🧹 已把 {user.display_name} 的{POINTS_NAME}歸零。"
                else:
                    msg = f"{user.display_name} 本來就沒有點數。"
        await interaction.response.send_message(
            msg, allowed_mentions=discord.AllowedMentions.none())

    @group.command(
        name="recompute",
        description="用目前費率重算所有人的點數（限 bot owner）")
    async def recompute(self, interaction: discord.Interaction):
        if not await self._guard(interaction):
            return
        if not await self.bot.is_owner(interaction.user):
            return await interaction.response.send_message(
                "只有 bot owner 能重算點數。", ephemeral=True)

        cfg = points_config(self.bot)
        voice_rate = cfg["voice_points_per_min"]
        msg_rate = cfg["message_points"]
        async with self._lock:
            data = _load()
            g = data.get(str(interaction.guild_id), {})
            for rec in g.values():
                rec["points"] = (rec.get("voice_min", 0) * voice_rate
                                 + rec.get("messages", 0) * msg_rate)
            if g:
                _save(data)
            count = len(g)

        await interaction.response.send_message(
            f"🧮 已用「語音 {voice_rate} 點/分 + 訊息 {msg_rate} 點/則」"
            f"重算 {count} 人的點數。",
            allowed_mentions=discord.AllowedMentions.none())

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
