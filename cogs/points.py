# -*- coding: utf-8 -*-
"""活躍度點數系統。名稱、費率與適用伺服器都在 config.yaml 的 `points:` 區塊。

- 進語音每 voice_minutes_per_point 分鐘 +1 點（排除 AFK 頻道 / 自己靜音或拒聽 /
  頻道只剩一個真人）。
- 每發一則訊息 +message_points 點（不限）。
- 每日明細另外存在 json/points_daily.json（先在記憶體累積，每 FLUSH_MINUTES
  分鐘落地一次），供 /points active 做滾動視窗查詢。預設永久保留，
  可用 points.history_days 限制天數。
- /points top 排行榜、/points view 個人、/points active 期間內達標名單、
  /points reset 歸零、/points recompute 依現行費率重算、
  !points_backfill 從歷史訊息回填每日明細（限 owner）。
"""
from __future__ import annotations

import asyncio
import datetime
import glob
import json
import logging
import os

import discord
import yaml
from discord import app_commands
from discord.ext import commands, tasks

import storage

logger = logging.getLogger(__name__)

CONFIG_PATH = "config.yaml"
POINTS_JSON = "json/points.json"
# 每日明細獨立一個檔。實測過：把它塞進 points.json 會讓每則訊息的
# read-modify-write 從 ~2ms 漲到 37ms（60 人 4 年）甚至 127ms（200 人 4 年），
# 而 storage 是同步 I/O，那會直接卡住 event loop。
DAILY_JSON = "json/points_daily.json"
LOGS_DIR = "logs"   # !points_import_logs 掃這底下的 *.jsonl
# !points_backfill 的續傳檔。掃完整歷史可能要跑好幾小時，中途掛掉不該白跑。
BACKFILL_STATE = "json/points_backfill_state.json"

TZ = datetime.timezone(datetime.timedelta(hours=8))
FLUSH_MINUTES = 5   # 每日明細在記憶體累積，每隔這麼久才寫一次檔

DEFAULTS = {
    "guild_id": None,        # None = 所有伺服器都啟用
    "display_name": "活躍點數",
    "emoji": "⭐",
    "voice_minutes_per_point": 3,  # 語音每 N 分鐘給 1 點
    "message_points": 1,
    "active_days": 30,             # /points active 預設回看幾天
    "active_threshold": 200,       # /points active 預設門檻
    "history_days": None,          # 每日明細保留幾天；null = 永久保留
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


# ── 每日明細 ──
# 結構：{guild_id: {user_id: {"YYYY-MM-DD": {"v": 語音點, "t": 文字點}}}}
# 舊格式一天是純 int（語音＋文字合併、無法回拆）——讀取時一律當文字，新資料才
# 會正確分開。_day_vt 把兩種格式都正規化成 (voice, text)。

def _day_vt(val):
    if isinstance(val, dict):
        return val.get("v", 0), val.get("t", 0)
    return 0, int(val or 0)   # 舊的合併 int → 當文字


def _day_total(val) -> int:
    v, t = _day_vt(val)
    return v + t


def _daily_add(daily: dict, guild_id, member_id, day: str, *,
               voice: int = 0, text: int = 0) -> None:
    if not (voice or text):
        return
    per_user = daily.setdefault(str(guild_id), {}).setdefault(str(member_id), {})
    v, t = _day_vt(per_user.get(day, 0))
    per_user[day] = {"v": v + voice, "t": t + text}


def _daily_merge(dst: dict, src: dict) -> None:
    """把 src 的每日點數累加進 dst（把記憶體暫存併進檔案內容）。"""
    for gid, users in src.items():
        for uid, per_day in users.items():
            for day, val in per_day.items():
                v, t = _day_vt(val)
                _daily_add(dst, gid, uid, day, voice=v, text=t)


def _daily_prune(daily: dict, today: str, keep_days) -> int:
    """丟掉太舊的分桶；keep_days 為 None 代表永久保留。回傳刪掉幾筆。

    ISO 日期字串的字典序就是時間序，所以直接比字串。
    """
    if not keep_days:
        return 0
    cutoff = (datetime.date.fromisoformat(today)
              - datetime.timedelta(days=int(keep_days))).isoformat()
    removed = 0
    for users in daily.values():
        for per_day in users.values():
            for d in [d for d in per_day if d < cutoff]:
                del per_day[d]
                removed += 1
    return removed


def _daily_recent(daily: dict, guild_id, today: str, days: int) -> dict:
    """回傳 {user_id: (語音點, 文字點)}，最近 days 天（含今天）；兩者皆 0 不列入。"""
    start = (datetime.date.fromisoformat(today)
             - datetime.timedelta(days=days - 1)).isoformat()
    out = {}
    for uid, per_day in (daily.get(str(guild_id)) or {}).items():
        v = t = 0
        for d, val in per_day.items():
            if d >= start:
                dv, dt = _day_vt(val)
                v += dv
                t += dt
        if v or t:
            out[uid] = (v, t)
    return out


def _count_from_logs(paths, guild_id, tz=TZ):
    """從訊息記錄檔統計每人每日的訊息「則數」（不看內容）。

    每行是一個 JSON 物件，需要 ts / guild_id / user_id 三個欄位——就是
    cogs_local/chatlog.py 寫出來的格式。用 message_id 去重，同一則被記兩次
    （例如同一個頻道被記錄過兩輪）不會重複計算。

    回傳 (counts, 讀到的行數, 壞行數, 重複行數)。
    """
    counts: dict = {}
    seen = set()
    lines = bad = dup = 0
    gid = str(guild_id)
    for path in paths:
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    lines += 1
                    try:
                        rec = json.loads(line)
                        if str(rec.get("guild_id")) != gid:
                            continue
                        uid = int(rec["user_id"])
                        ts = datetime.datetime.fromisoformat(rec["ts"])
                    except (ValueError, KeyError, TypeError):
                        bad += 1
                        continue
                    mid = rec.get("message_id")
                    if mid is not None:
                        if mid in seen:
                            dup += 1
                            continue
                        seen.add(mid)
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=tz)
                    day = _today(ts.astimezone(tz))
                    per_day = counts.setdefault(uid, {})
                    per_day[day] = per_day.get(day, 0) + 1
        except OSError:
            continue
    return counts, lines, bad, dup


def _migrate_inline_daily(points_data: dict, daily: dict) -> int:
    """把舊版存在 points.json 記錄裡的 "daily" 欄位搬到獨立檔。

    回傳被拔掉 daily 欄位的紀錄數（含空的——留著只會讓 points.json 白白變大，
    而且下次還會被誤認成需要遷移）。搬完之後再呼叫就會回 0。
    """
    touched = 0
    for gid, users in points_data.items():
        for uid, rec in users.items():
            if "daily" not in rec:
                continue
            inline = rec.pop("daily") or {}
            for day, pts in inline.items():
                _daily_add(daily, gid, uid, day, text=pts)  # 舊 inline 是合併值 → 當文字
            touched += 1
    return touched


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
           voice_min=0, minutes_per_point=None):
    """累加累計數字，回傳這次實際加到的點數。

    語音採「每 minutes_per_point 分鐘 1 點」：先累加分鐘數，再看跨過了幾個
    整數倍才給點。這樣 3 分鐘 1 點不需要把點數變成小數。

    每日明細不在這裡處理——那份走 DAILY_JSON，由 cog 在記憶體累積後定期落地。
    """
    g = data.setdefault(str(guild_id), {})
    rec = g.get(str(member_id))
    if rec is None:
        rec = {"name": name, "points": 0, "messages": 0, "voice_min": 0}
        g[str(member_id)] = rec
    rec["name"] = name

    gained = points
    if voice_min:
        before = rec["voice_min"]
        rec["voice_min"] = before + voice_min
        if minutes_per_point:
            gained += (rec["voice_min"] // minutes_per_point
                       - before // minutes_per_point)

    rec["messages"] += messages
    rec["points"] += gained
    return gained


def _merge_backfill(daily: dict, guild_id, counts: dict, msg_points: int):
    """把回填掃到的 {uid: {day: 訊息數}} 併進每日明細。

    已經有紀錄的日子一律不動——那些是即時累積來的、裡面含語音點數，覆蓋
    下去會把語音的部分弄丟；同時這也讓重跑同一段期間是冪等的。

    回傳 (寫入的人日數, 跳過的人日數)。
    """
    g = daily.setdefault(str(guild_id), {})
    filled = skipped = 0
    for uid, per_day in counts.items():
        stored = g.setdefault(str(uid), {})
        for day, n in per_day.items():
            if day in stored:
                skipped += 1
                continue
            stored[day] = {"v": 0, "t": n * msg_points}  # 回填只有訊息 → 純文字
            filled += 1
    return filled, skipped


def _voice_channel_eligible(num_humans: int, is_afk: bool) -> bool:
    """頻道層級資格：至少兩個真人、且不是 AFK 頻道。"""
    return num_humans >= 2 and not is_afk


def _member_voice_eligible(self_mute: bool, self_deaf: bool) -> bool:
    """個人層級資格：沒有自己靜音或拒聽。"""
    return not (self_mute or self_deaf)


def total_points(rec: dict) -> int:
    """顯示用的總點數 = 即時累積 + 從歷史訊息回填的部分。

    兩者分開存的原因：即時那份是點數系統上線後一則一則加起來的，歷史那份是
    事後掃回來的。混在同一個欄位的話，重跑回填就會重複累加、而且無從還原。
    分開之後 `!points_apply_history` 可以直接覆寫歷史欄位，天生冪等。
    """
    return rec.get("points", 0) + rec.get("history_points", 0)


def total_messages(rec: dict) -> int:
    return rec.get("messages", 0) + rec.get("history_messages", 0)


def points_breakdown(rec: dict, message_points: int):
    """把總點數拆成 (語音點數, 文字點數)。

    文字點數 = 總訊息數 × 每則點數（含回填的歷史訊息——歷史只回填得到訊息，
    語音無法回溯）。語音點數 = 總點數扣掉文字點數。用相減而不是直接算
    voice_min // 費率，是因為費率若中途調過，voice_min 換算會對不上實際累積的
    點數；相減能保證「語音 + 文字 = 總點數」永遠成立。message_points 若調大到
    讓文字點數超過總點數（罕見），就夾住文字、語音記 0，不會出現負數。
    """
    total = total_points(rec)
    text_pts = min(total_messages(rec) * message_points, total)
    return total - text_pts, text_pts


def _leaderboard(data: dict, guild_id):
    """回傳依點數由高到低排序的 [(user_id, record), ...]。"""
    g = data.get(str(guild_id), {})
    return sorted(g.items(), key=lambda kv: total_points(kv[1]), reverse=True)


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
                f"{tag} <@{uid}> — **{total_points(rec)}** 點"
                f"（🎙️{rec.get('voice_min', 0)} 分 / 💬{total_messages(rec)} 則）"
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
        self._daily_lock = storage.lock_for(DAILY_JSON)
        # 每日明細先在記憶體累積，由 flush_daily 定期落地。每則訊息都去
        # read-modify-write 一份完整歷史檔的話，光 I/O 就會卡住 event loop。
        self._pending: dict = {}
        self.voice_tick.start()
        self.flush_daily.start()

    def cog_unload(self):
        if self.voice_tick.is_running():
            self.voice_tick.cancel()
        if self.flush_daily.is_running():
            self.flush_daily.cancel()
        # 卸載/重載前把還沒落地的部分寫掉，不然這段時間的明細會不見。
        if self._pending:
            self.bot.loop.create_task(self._flush_now())

    # --- 每日明細的記憶體暫存 ---

    def _note_daily(self, guild_id, member_id, day: str, *,
                    voice: int = 0, text: int = 0) -> None:
        if voice or text:
            _daily_add(self._pending, guild_id, member_id, day, voice=voice, text=text)

    def _daily_view(self, guild_id) -> dict:
        """檔案內容 + 還沒落地的暫存，合起來的即時視圖。"""
        daily = storage.read_json(DAILY_JSON)
        _daily_merge(daily, self._pending)
        return daily

    async def _flush_now(self) -> int:
        """把暫存併進檔案並清空。回傳寫入的人數。"""
        if not self._pending:
            return 0
        pending, self._pending = self._pending, {}
        async with self._daily_lock:
            daily = storage.read_json(DAILY_JSON)
            _daily_merge(daily, pending)
            _daily_prune(daily, _today(), points_config(self.bot)["history_days"])
            storage.write_json_atomic(DAILY_JSON, daily)
        return sum(len(v) for v in pending.values())

    async def _migrate_once(self) -> None:
        """把舊版塞在 points.json 裡的 inline daily 搬到獨立檔。啟動時跑一次。

        先在 points.json 那側 pop 並存檔，再併進 daily 檔——順序反過來的話，
        中間掛掉會在下次啟動重複累加；照這個順序最壞只是少掉那批明細。
        """
        popped: dict = {}
        async with self._lock:
            data = _load()
            moved = _migrate_inline_daily(data, popped)
            if moved:
                _save(data)
        if not moved:
            return
        async with self._daily_lock:
            daily = storage.read_json(DAILY_JSON)
            _daily_merge(daily, popped)
            storage.write_json_atomic(DAILY_JSON, daily)
        logger.info("已清掉 %d 筆紀錄的舊 inline daily 欄位（明細移到 %s）",
                    moved, DAILY_JSON)

    @tasks.loop(minutes=FLUSH_MINUTES)
    async def flush_daily(self):
        await self._flush_now()

    @flush_daily.before_loop
    async def before_flush_daily(self):
        await self.bot.wait_until_ready()
        await self._migrate_once()

    @flush_daily.error
    async def flush_daily_error(self, error):
        logger.error("flush_daily error: %s", error)

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
                            gained = _award(
                                data, guild.id, m.id, m.display_name, voice_min=1,
                                minutes_per_point=cfg["voice_minutes_per_point"])
                            self._note_daily(guild.id, m.id, today, voice=gained)
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
            gained = _award(data, message.guild.id, message.author.id,
                            message.author.display_name,
                            points=cfg["message_points"], messages=1)
            _save(data)
        self._note_daily(message.guild.id, message.author.id, _today(), text=gained)

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
        voice_pts, text_pts = points_breakdown(rec, points_config(self.bot)["message_points"])
        embed = discord.Embed(
            title=f"{POINTS_EMOJI} {POINTS_NAME}",
            description=(
                f"{target.mention}\n"
                f"**{total_points(rec)}** 點 · 第 **{rank}** 名（共 {len(board)} 人）\n"
                f"🎙️ 語音 {voice_pts} 點（{rec.get('voice_min', 0)} 分鐘）\n"
                f"💬 文字 {text_pts} 點（{total_messages(rec)} 則）"
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
        if days < 1:
            return await interaction.response.send_message(
                "天數至少要 1 天。", ephemeral=True)
        if threshold < 0:
            return await interaction.response.send_message(
                "門檻不能是負數。", ephemeral=True)

        recent = _daily_recent(self._daily_view(interaction.guild_id),
                               interaction.guild_id, _today(), days)
        rows = sorted(((uid, v, t) for uid, (v, t) in recent.items() if v + t >= threshold),
                      key=lambda r: r[1] + r[2], reverse=True)

        if not rows:
            return await interaction.response.send_message(
                f"最近 {days} 天沒有人的{POINTS_NAME}達到 **{threshold}** 點。\n"
                f"（每日明細是從這個功能上線後才開始記的，之前的資料算不進來）",
                ephemeral=True)

        lines = [
            f"**{i}.** <@{uid}> — **{v + t}** 點（🎙️{v} / 💬{t}）"
            for i, (uid, v, t) in enumerate(rows[:25], start=1)
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
                # 只重算即時累積的部分；history_points 是回填來的，不受費率影響
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
    async def points_backfill(self, ctx: commands.Context, days: str = "all",
                              mode: str = ""):
        """從歷史訊息回填每日明細。加上 `dry` 只預覽不寫入。

        用法：`!points_backfill`（整個伺服器的歷史）、`!points_backfill 90`、
        `!points_backfill all dry`、`!points_backfill all resume`（接續上次）

        只回填訊息。**語音無法回填**——Discord 不保留語音在線的歷史，
        API 也沒有任何查詢端點，所以過去的語音分鐘數永遠補不回來。
        """
        cfg = points_config(self.bot)
        if not points_enabled(self.bot, ctx.guild.id):
            return await ctx.send("此功能未在這個伺服器啟用。")

        if str(days).lower() in ("all", "0", "full"):
            cutoff, span = None, "全部歷史"
        else:
            try:
                n = int(days)
            except ValueError:
                return await ctx.send("天數請給數字，或用 `all` 掃全部歷史。")
            if n < 1:
                return await ctx.send("天數至少要 1 天。")
            cutoff = datetime.datetime.now(TZ) - datetime.timedelta(days=n)
            span = f"最近 {n} 天"

        keep = cfg["history_days"]
        if cutoff is None and keep:
            return await ctx.send(
                f"設定 points.history_days = {keep}，掃了全部歷史也會在寫入時被"
                f"修剪掉。要保留完整歷史請把它設成 null。")

        mode_l = mode.lower()
        dry = mode_l.startswith("dry")
        resume = "resume" in mode_l
        msg_points = cfg["message_points"]
        MAX_SCAN = 5_000_000

        resumed = storage.read_json(BACKFILL_STATE) if resume else {}
        if resumed and resumed.get("guild_id") != str(ctx.guild.id):
            resumed = {}   # 別把別的伺服器的進度接上來
        counts: dict[int, dict[str, int]] = {
            int(k): v for k, v in (resumed.get("counts") or {}).items()}
        scanned = int(resumed.get("scanned") or 0)
        skipped_sources = 0

        status = await ctx.send(
            f"🔎 開始掃描{span}的訊息…（量大時會跑好幾小時，慢慢等）\n"
            f"中途掛掉可用 `!points_backfill {days} resume` 從上次進度接著跑。")
        done = set(resumed.get("done") or [])
        if done:
            await ctx.send(f"↩️ 續傳：已完成 {len(done)} 個來源，接著跑剩下的。")

        async def save_state():
            storage.write_json_atomic(BACKFILL_STATE, {
                "guild_id": str(ctx.guild.id),
                "span": span,
                "done": sorted(done),
                "scanned": scanned,
                "counts": {str(k): v for k, v in counts.items()},
            })

        async for source in self._iter_history_sources(ctx.guild):
            if source.id in done:
                continue
            src_name = getattr(source, "name", source.id)
            try:
                async for m in source.history(limit=None, after=cutoff,
                                              oldest_first=True):
                    scanned += 1
                    if not (m.author.bot or member_excluded(m.author, cfg)):
                        day = _today(m.created_at.astimezone(TZ))
                        per_day = counts.setdefault(m.author.id, {})
                        per_day[day] = per_day.get(day, 0) + 1
                    # 掃一百萬則要跑好幾小時，中途得看得到進度——Discord 訊息每
                    # 2 萬則更新一次，log 也記一筆（docker logs 看得到）。
                    if scanned % 20_000 == 0:
                        logger.info("backfill: 已讀 %s 則，目前在 #%s", scanned, src_name)
                        try:
                            await status.edit(
                                content=f"🔎 掃描中…已讀 {scanned:,} 則（目前 #{src_name}）")
                        except discord.HTTPException:
                            pass
                    if scanned >= MAX_SCAN:
                        break
            except (discord.Forbidden, discord.HTTPException):
                skipped_sources += 1
                continue
            done.add(source.id)
            await save_state()   # 每掃完一個來源存一次，掛掉最多只丟這一個
            if scanned >= MAX_SCAN:
                await ctx.send(f"⚠️ 已達掃描上限 {MAX_SCAN:,} 則，提前停止。")
                break

        total_msgs = sum(sum(d.values()) for d in counts.values())
        head = (f"掃了 {scanned:,} 則訊息，其中 {total_msgs:,} 則可計點，"
                f"涉及 {len(counts)} 人。")
        if skipped_sources:
            head += f"（{skipped_sources} 個頻道/討論串沒有讀取權限，已略過）"

        if dry:
            return await ctx.send(f"🧪 **預覽（未寫入）**\n{head}")

        # 先把記憶體暫存落地，否則 flush 時會蓋回一份沒有回填內容的舊檔。
        await self._flush_now()
        async with self._daily_lock:
            daily = storage.read_json(DAILY_JSON)
            filled, skipped_days = _merge_backfill(
                daily, ctx.guild.id, counts, msg_points)
            _daily_prune(daily, _today(), keep)
            storage.write_json_atomic(DAILY_JSON, daily)
        size = os.path.getsize(DAILY_JSON) if os.path.exists(DAILY_JSON) else 0
        try:
            os.remove(BACKFILL_STATE)   # 成功寫入才清掉續傳檔
        except OSError:
            pass

        await ctx.send(
            f"✅ **回填完成**\n{head}\n"
            f"寫入 {filled:,} 個人日，跳過 {skipped_days:,} 個已有紀錄的人日。\n"
            f"`{DAILY_JSON}` 現在 {size/1024:.0f} KB。\n"
            f"⚠️ 只回填了訊息；語音分鐘數無法回溯（Discord 不保留語音歷史）。\n"
            f"累計總點數與訊息數沒有更動，只有 `/points active` 用的每日明細被補上。"
        )

    @commands.command(name="points_import_logs", hidden=True)
    @commands.is_owner()
    @commands.guild_only()
    async def points_import_logs(self, ctx: commands.Context, mode: str = ""):
        """從本機訊息記錄檔統計「每天幾則」，回填每日明細。加 `dry` 只預覽。

        讀 logs/**/*.jsonl，每行需要 ts / guild_id / user_id 三個欄位——就是
        cogs_local/chatlog.py 寫出來的格式。只數則數，不看訊息內容。

        跟 !points_backfill 的差別：這個是讀本機檔案，秒完、不打 Discord API，
        但只涵蓋記錄檔存在的那段期間；!points_backfill 走 API 能拿到完整歷史
        但很慢。兩個都遵守「已有紀錄的日子不覆蓋」，可以先跑這個再跑那個。
        """
        cfg = points_config(self.bot)
        if not points_enabled(self.bot, ctx.guild.id):
            return await ctx.send("此功能未在這個伺服器啟用。")

        paths = sorted(glob.glob(os.path.join(LOGS_DIR, "**", "*.jsonl"),
                                 recursive=True))
        if not paths:
            return await ctx.send(f"`{LOGS_DIR}/` 底下找不到任何 .jsonl 記錄檔。")

        loop = asyncio.get_event_loop()
        counts, lines, bad, dup = await loop.run_in_executor(
            None, _count_from_logs, paths, ctx.guild.id)

        # 記錄檔只有 user_id，訪客判定要靠現在的成員資料；查不到就照算。
        dropped = 0
        for uid in list(counts):
            member = ctx.guild.get_member(uid)
            if member is not None and member_excluded(member, cfg):
                del counts[uid]
                dropped += 1

        total = sum(sum(d.values()) for d in counts.values())
        days_seen = {d for per in counts.values() for d in per}
        head = (f"讀了 {len(paths)} 個檔案 / {lines:,} 行，統計出 {total:,} 則、"
                f"{len(counts)} 人、橫跨 {len(days_seen)} 天"
                f"（{min(days_seen)} ~ {max(days_seen)}）。" if days_seen else
                f"讀了 {len(paths)} 個檔案 / {lines:,} 行，沒有這個伺服器的資料。")
        if bad:
            head += f" 略過 {bad} 行壞資料。"
        if dup:
            head += f" 去重 {dup} 行。"
        if dropped:
            head += f" 排除 {dropped} 位訪客。"

        if not counts:
            return await ctx.send(head)
        if mode.lower().startswith("dry"):
            return await ctx.send(f"🧪 **預覽（未寫入）**\n{head}")

        await self._flush_now()
        async with self._daily_lock:
            daily = storage.read_json(DAILY_JSON)
            filled, skipped = _merge_backfill(
                daily, ctx.guild.id, counts, cfg["message_points"])
            _daily_prune(daily, _today(), cfg["history_days"])
            storage.write_json_atomic(DAILY_JSON, daily)

        await ctx.send(
            f"✅ **匯入完成**\n{head}\n"
            f"寫入 {filled:,} 個人日，跳過 {skipped:,} 個已有紀錄的人日。\n"
            f"只回填了訊息則數；語音無法回溯。累計總點數暫時不動——"
            f"要併進總點數請跑 `!points_apply_history <點數系統上線日>`。"
        )

    @commands.command(name="points_apply_history", hidden=True)
    @commands.is_owner()
    @commands.guild_only()
    async def points_apply_history(self, ctx: commands.Context,
                                   before: str = None, mode: str = ""):
        """把 `before` 之前的每日明細併進總點數。加 `dry` 只預覽。

        用法：`!points_apply_history 2026-06-15`

        `before` 要填**點數系統開始即時計點的那一天**。那天之後的訊息早就一則
        一則加進累計數字了，再加一次就是重複計算——所以只取那天之前的。

        寫進獨立的 history_points / history_messages 欄位（覆寫而非累加），
        所以重跑同一個日期結果完全相同。顯示的總點數 = 即時累積 + 這兩個欄位。
        """
        if not points_enabled(self.bot, ctx.guild.id):
            return await ctx.send("此功能未在這個伺服器啟用。")
        if not before:
            return await ctx.send(
                "要指定分界日：`!points_apply_history YYYY-MM-DD`\n"
                "填點數系統開始計點的那一天，那天（含）之後的不會被併入。")
        try:
            cutoff = datetime.date.fromisoformat(before.strip()).isoformat()
        except ValueError:
            return await ctx.send("日期格式請用 `YYYY-MM-DD`。")

        cfg = points_config(self.bot)
        msg_points = max(1, int(cfg["message_points"]))
        await self._flush_now()
        daily = storage.read_json(DAILY_JSON).get(str(ctx.guild.id)) or {}
        if not daily:
            return await ctx.send(
                "還沒有每日明細，先跑 `!points_import_logs` 或 `!points_backfill`。")

        hist = {}
        for uid, per_day in daily.items():
            got = sum(_day_total(val) for d, val in per_day.items() if d < cutoff)
            if got:
                hist[uid] = got

        if not hist:
            return await ctx.send(f"{cutoff} 之前沒有任何每日明細可以併入。")

        preview = (f"{cutoff} 之前共 {sum(hist.values()):,} 點、{len(hist)} 人。"
                   f"（{cutoff} 當天及之後的不動，那些已經在累計數字裡）")
        if mode.lower().startswith("dry"):
            return await ctx.send(f"🧪 **預覽（未寫入）**\n{preview}")

        async with self._lock:
            data = _load()
            g = data.setdefault(str(ctx.guild.id), {})
            for uid, got in hist.items():
                rec = g.get(uid)
                if rec is None:
                    rec = {"name": str(uid), "points": 0, "messages": 0,
                           "voice_min": 0}
                    g[uid] = rec
                # 覆寫而非累加 → 重跑冪等
                rec["history_points"] = got
                rec["history_messages"] = got // msg_points
            _save(data)

        board = _leaderboard(_load(), ctx.guild.id)
        top = "\n".join(
            f"  {i}. <@{uid}> — {total_points(rec):,} 點"
            for i, (uid, rec) in enumerate(board[:3], start=1))
        await ctx.send(
            f"✅ **已併入歷史**\n{preview}\n目前前三名：\n{top}",
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
