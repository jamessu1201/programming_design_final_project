# -*- coding: utf-8 -*-
"""活躍度點數系統。名稱、費率與適用伺服器都在 config.yaml 的 `points:` 區塊。

- 進語音每 voice_minutes_per_point 分鐘 +1 點（排除 AFK 頻道 / 自己靜音或拒聽 /
  頻道只剩一個真人）。
- 每發一則訊息 +message_points 點（不限）。
- 每個人另外保留最近 HISTORY_DAYS 天的每日明細，供 /points active 做滾動視窗查詢。
- /points top 排行榜、/points view 個人、/points active 期間內達標名單、
  /points reset 歸零、/points recompute 依現行費率重算。
"""
from __future__ import annotations

import datetime
import logging

import discord
import yaml
from discord import app_commands
from discord.ext import commands, tasks

import storage

logger = logging.getLogger(__name__)

CONFIG_PATH = "config.yaml"
POINTS_JSON = "json/points.json"

TZ = datetime.timezone(datetime.timedelta(hours=8))
HISTORY_DAYS = 100  # 每人保留幾天的每日明細，給 /points active 的滾動視窗用

DEFAULTS = {
    "guild_id": None,        # None = 所有伺服器都啟用
    "display_name": "活躍點數",
    "emoji": "⭐",
    "voice_minutes_per_point": 3,  # 語音每 N 分鐘給 1 點
    "message_points": 1,
    "active_days": 30,             # /points active 預設回看幾天
    "active_threshold": 200,       # /points active 預設門檻
    "exclude_guests": True,  # 自動排除 Discord 官方的訪客（MemberFlags.guest）
    "excluded_roles": [],    # 額外不計點的身分組 ID（自訂的訪客身分組之類的）
}

LEADERBOARD_SIZE = 15
MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}


# ── 設定 ──

def points_config(bot) -> dict:
    """執行期設定。bot.config 是權威來源（!deploy 會重載它），缺的補預設。"""
    cfg = dict(DEFAULTS)
    raw = (getattr(bot, "config", None) or {}).get("points") or {}
    if "voice_points_per_min" in raw:
        logger.warning(
            "config.yaml 的 points.voice_points_per_min 已停用，"
            "請改成 voice_minutes_per_point（語音每 N 分鐘 1 點）。目前用預設 %s。",
            DEFAULTS["voice_minutes_per_point"])
    cfg.update(raw)
    return cfg


def _today(now: datetime.datetime | None = None) -> str:
    return (now or datetime.datetime.now(TZ)).date().isoformat()


def _prune_daily(rec: dict, today: str, keep_days: int = HISTORY_DAYS) -> None:
    """丟掉太舊的每日分桶。ISO 日期字串的字典序就是時間序。"""
    daily = rec.get("daily")
    if not daily or len(daily) <= keep_days:
        return
    cutoff = (datetime.date.fromisoformat(today)
              - datetime.timedelta(days=keep_days)).isoformat()
    for d in [d for d in daily if d < cutoff]:
        del daily[d]


def _recent_points(rec: dict, today: str, days: int) -> int:
    """最近 days 天（含今天）累積的點數。沒有每日明細的舊資料回 0。"""
    start = (datetime.date.fromisoformat(today)
             - datetime.timedelta(days=days - 1)).isoformat()
    return sum(v for d, v in (rec.get("daily") or {}).items() if d >= start)


def points_enabled(bot, guild_id) -> bool:
    """guild_id 設 null（None）代表不限伺服器。"""
    target = points_config(bot)["guild_id"]
    return target is None or guild_id == target


def member_excluded(member, cfg) -> bool:
    """這個人該不該被排除在計點之外。訊息與語音都適用。

    兩個來源：
    1. Discord 官方的訪客旗標 MemberFlags.guest（IS_GUEST，只能進被邀請的
       那個語音頻道的人）——不用設定，自動辨識。
    2. config 的 excluded_roles，給自己開的訪客身分組之類的用。

    已經累積的點數不會被動到——要清掉用 `/points reset <user>`。
    """
    if cfg.get("exclude_guests", True):
        # User（非 Member）沒有 flags，getattr 兩層防呆。
        if getattr(getattr(member, "flags", None), "guest", False):
            return True

    excluded = cfg.get("excluded_roles") or []
    if not excluded:
        return False
    role_ids = {r.id for r in getattr(member, "roles", ())}
    if not role_ids:
        return False
    for rid in excluded:
        try:
            if int(rid) in role_ids:
                return True
        except (TypeError, ValueError):
            logger.warning("points.excluded_roles 有非數字的值：%r", rid)
    return False


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

def _award(data: dict, guild_id, member_id, name, *, points=0, messages=0,
           voice_min=0, minutes_per_point=None, day=None):
    """累加明細，回傳這次實際加到的點數。

    語音採「每 minutes_per_point 分鐘 1 點」：先累加分鐘數，再看跨過了幾個
    整數倍才給點。這樣 3 分鐘 1 點不需要把點數變成小數。

    給了 day 就同時記進 rec["daily"][day]，/points active 的滾動視窗靠它。
    """
    g = data.setdefault(str(guild_id), {})
    rec = g.get(str(member_id))
    if rec is None:
        rec = {"name": name, "points": 0, "messages": 0, "voice_min": 0, "daily": {}}
        g[str(member_id)] = rec
    rec["name"] = name
    rec.setdefault("daily", {})   # 舊資料沒有這個欄位

    gained = points
    if voice_min:
        before = rec["voice_min"]
        rec["voice_min"] = before + voice_min
        if minutes_per_point:
            gained += (rec["voice_min"] // minutes_per_point
                       - before // minutes_per_point)

    rec["messages"] += messages
    rec["points"] += gained
    if gained and day:
        rec["daily"][day] = rec["daily"].get(day, 0) + gained
        _prune_daily(rec, day)
    return gained


def _merge_backfill(data: dict, guild_id, counts: dict, names: dict,
                    msg_points: int, today: str):
    """把回填掃到的 {uid: {day: 訊息數}} 併進每日明細。

    已經有紀錄的日子一律不動——那些是即時累積來的、裡面含語音點數，覆蓋
    下去會把語音的部分弄丟；同時這也讓重跑同一段期間是冪等的。

    回傳 (寫入的人日數, 跳過的人日數)。
    """
    g = data.setdefault(str(guild_id), {})
    filled = skipped = 0
    for uid, per_day in counts.items():
        rec = g.get(str(uid))
        if rec is None:
            rec = {"name": names.get(uid, str(uid)), "points": 0,
                   "messages": 0, "voice_min": 0, "daily": {}}
            g[str(uid)] = rec
        rec.setdefault("daily", {})
        for day, n in per_day.items():
            if day in rec["daily"]:
                skipped += 1
                continue
            rec["daily"][day] = n * msg_points
            filled += 1
        _prune_daily(rec, today)
    return filled, skipped


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
        today = _today()
        async with self._lock:
            data = _load()
            changed = False
            for guild in guilds:
                afk_id = guild.afk_channel.id if guild.afk_channel else None
                for vc in guild.voice_channels:
                    # 被排除的人仍算在「頻道至少兩個真人」裡：訪客陪著也是陪著，
                    # 有人作伴的那位照常累積，只是訪客自己不拿點。
                    humans = [m for m in vc.members if not m.bot]
                    if not _voice_channel_eligible(len(humans), vc.id == afk_id):
                        continue
                    for m in humans:
                        if member_excluded(m, cfg):
                            continue
                        vs = m.voice
                        if vs and _member_voice_eligible(vs.self_mute, vs.self_deaf):
                            _award(data, guild.id, m.id, m.display_name,
                                   voice_min=1,
                                   minutes_per_point=cfg["voice_minutes_per_point"],
                                   day=today)
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
        if member_excluded(message.author, cfg):
            return
        async with self._lock:
            data = _load()
            _award(data, message.guild.id, message.author.id,
                   message.author.display_name,
                   points=cfg["message_points"], messages=1, day=_today())
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

    @group.command(name="active", description=f"列出一段期間內{POINTS_NAME}超過門檻的人")
    @app_commands.describe(
        days="回看幾天（預設看設定值，通常 30）",
        threshold="點數門檻（預設看設定值，通常 200）",
    )
    async def active(self, interaction: discord.Interaction,
                     days: int = None, threshold: int = None):
        if not await self._guard(interaction):
            return
        cfg = points_config(self.bot)
        days = cfg["active_days"] if days is None else days
        threshold = cfg["active_threshold"] if threshold is None else threshold
        if not 1 <= days <= HISTORY_DAYS:
            return await interaction.response.send_message(
                f"天數請介於 1～{HISTORY_DAYS}（每日明細只保留這麼久）。", ephemeral=True)
        if threshold < 0:
            return await interaction.response.send_message(
                "門檻不能是負數。", ephemeral=True)

        today = _today()
        g = _load().get(str(interaction.guild_id), {})
        rows = []
        for uid, rec in g.items():
            got = _recent_points(rec, today, days)
            if got >= threshold:
                rows.append((uid, rec, got))
        rows.sort(key=lambda r: r[2], reverse=True)

        if not rows:
            return await interaction.response.send_message(
                f"最近 {days} 天沒有人的{POINTS_NAME}達到 **{threshold}** 點。\n"
                f"（每日明細是從這個功能上線後才開始記的，之前的資料算不進來）",
                ephemeral=True)

        lines = [
            f"**{i}.** <@{uid}> — **{got}** 點"
            for i, (uid, rec, got) in enumerate(rows[:25], start=1)
        ]
        if len(rows) > 25:
            lines.append(f"…還有 {len(rows) - 25} 人")

        embed = discord.Embed(
            title=f"{POINTS_EMOJI} 最近 {days} 天 {POINTS_NAME} ≥ {threshold}",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )
        embed.set_footer(text=f"共 {len(rows)} 人達標")
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
        mpp = max(1, int(cfg["voice_minutes_per_point"]))
        msg_rate = cfg["message_points"]
        async with self._lock:
            data = _load()
            g = data.get(str(interaction.guild_id), {})
            for rec in g.values():
                rec["points"] = (rec.get("voice_min", 0) // mpp
                                 + rec.get("messages", 0) * msg_rate)
            if g:
                _save(data)
            count = len(g)

        await interaction.response.send_message(
            f"🧮 已用「語音 {mpp} 分鐘 1 點 + 訊息 {msg_rate} 點/則」"
            f"重算 {count} 人的點數（每日明細不受影響）。",
            allowed_mentions=discord.AllowedMentions.none())

    # --- 從歷史訊息回填每日明細（限 bot owner） ---

    async def _iter_history_sources(self, guild):
        """所有掃得到歷史訊息的地方：文字/語音頻道本身、它們的討論串
        （含已封存的）、以及論壇底下的貼文。"""
        for ch in list(guild.text_channels) + list(guild.voice_channels):
            yield ch
            for th in getattr(ch, "threads", ()):
                yield th
            if hasattr(ch, "archived_threads"):
                try:
                    async for th in ch.archived_threads(limit=None):
                        yield th
                except (discord.Forbidden, discord.HTTPException):
                    pass
        for fch in getattr(guild, "forums", ()):
            for th in fch.threads:
                yield th
            try:
                async for th in fch.archived_threads(limit=None):
                    yield th
            except (discord.Forbidden, discord.HTTPException):
                pass

    @commands.command(name="points_backfill", hidden=True)
    @commands.is_owner()
    @commands.guild_only()
    async def points_backfill(self, ctx: commands.Context, days: int = 90,
                              mode: str = ""):
        """從歷史訊息回填每日明細。加上 `dry` 只預覽不寫入。

        用法：`!points_backfill 90` / `!points_backfill 90 dry`

        只回填訊息。**語音無法回填**——Discord 不保留語音在線的歷史，
        API 也沒有任何查詢端點，所以過去的語音分鐘數永遠補不回來。
        """
        cfg = points_config(self.bot)
        if not points_enabled(self.bot, ctx.guild.id):
            return await ctx.send("此功能未在這個伺服器啟用。")
        if not 1 <= days <= HISTORY_DAYS:
            return await ctx.send(f"天數請介於 1～{HISTORY_DAYS}。")

        dry = mode.lower().startswith("dry")
        msg_points = cfg["message_points"]
        today = _today()
        cutoff = datetime.datetime.now(TZ) - datetime.timedelta(days=days)

        counts: dict[int, dict[str, int]] = {}
        names: dict[int, str] = {}
        scanned = skipped_sources = 0
        MAX_SCAN = 300_000

        status = await ctx.send(f"🔎 開始掃描最近 {days} 天的訊息…（可能要幾分鐘）")
        async for source in self._iter_history_sources(ctx.guild):
            try:
                async for m in source.history(limit=None, after=cutoff,
                                              oldest_first=True):
                    scanned += 1
                    if m.author.bot or member_excluded(m.author, cfg):
                        continue
                    day = _today(m.created_at.astimezone(TZ))
                    per_day = counts.setdefault(m.author.id, {})
                    per_day[day] = per_day.get(day, 0) + 1
                    names[m.author.id] = m.author.display_name
                    if scanned >= MAX_SCAN:
                        break
            except (discord.Forbidden, discord.HTTPException):
                skipped_sources += 1
                continue
            if scanned >= MAX_SCAN:
                await ctx.send(f"⚠️ 已達掃描上限 {MAX_SCAN:,} 則，提前停止。")
                break
            if scanned and scanned % 20_000 < 200:
                try:
                    await status.edit(content=f"🔎 掃描中…已讀 {scanned:,} 則")
                except discord.HTTPException:
                    pass

        total_msgs = sum(sum(d.values()) for d in counts.values())
        head = (f"掃了 {scanned:,} 則訊息，其中 {total_msgs:,} 則可計點，"
                f"涉及 {len(counts)} 人。")
        if skipped_sources:
            head += f"（{skipped_sources} 個頻道/討論串沒有讀取權限，已略過）"

        if dry:
            return await ctx.send(f"🧪 **預覽（未寫入）**\n{head}")

        async with self._lock:
            data = _load()
            filled, skipped_days = _merge_backfill(
                data, ctx.guild.id, counts, names, msg_points, today)
            _save(data)

        await ctx.send(
            f"✅ **回填完成**\n{head}\n"
            f"寫入 {filled} 個人日，跳過 {skipped_days} 個已有紀錄的人日。\n"
            f"⚠️ 只回填了訊息；語音分鐘數無法回溯（Discord 不保留語音歷史）。\n"
            f"累計總點數與訊息數沒有更動，只有 `/points active` 用的每日明細被補上。"
        )

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
