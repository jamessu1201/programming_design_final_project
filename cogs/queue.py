# -*- coding: utf-8 -*-
"""排隊系統：一個 guild 可以有多個具名 queue。

規則：
- 任何人都能把資訊加到隊尾（add）。
- 中間/尾端的項目只有放它的人能拿走自己的那筆（take）。
- 隊頭（最前面那筆）任何人都可以移除（pop）。
"""
from __future__ import annotations

import datetime
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

import storage

logger = logging.getLogger(__name__)

QUEUES_JSON = "json/queues.json"

MAX_NAME = 50
MAX_CONTENT = 500
MAX_ITEMS = 100  # 單一 queue 上限，防濫用

TZ = datetime.timezone(datetime.timedelta(hours=8))
DEFAULT_COOLDOWN_DAYS = 30  # 預設冷卻一個月
FIRE_HOUR = 12  # 用 /queue setnext 只給日期時，預設當天中午（UTC+8）


# ── 持久化（純函式，方便測試） ──

def _load() -> dict:
    return storage.read_json(QUEUES_JSON)


def _save(data: dict) -> None:
    storage.write_json_atomic(QUEUES_JSON, data)


# ── queue 核心邏輯（純函式，operate on passed dict） ──

def _get_queue(data: dict, guild_id, name: str):
    return data.get(str(guild_id), {}).get(name)


def _cleanup_if_empty(data: dict, guild_id, name: str) -> None:
    gid = str(guild_id)
    g = data.get(gid)
    if g and name in g and not g[name]["items"]:
        # 有自動冷卻設定的 queue 即使空了也保留，否則冷卻設定會被刪掉。
        if g[name].get("auto"):
            return
        del g[name]
        if not g:
            del data[gid]


def _enqueue(data: dict, guild_id, name, user_id, user_name, content, ts,
             max_items=MAX_ITEMS):
    """加到隊尾。回傳 (item, position 1-based)，queue 滿了回 None。"""
    g = data.setdefault(str(guild_id), {})
    q = g.get(name)
    if q is None:
        q = {"next_id": 1, "items": []}
        g[name] = q
    if len(q["items"]) >= max_items:
        return None
    item = {
        "id": q["next_id"],
        "user_id": user_id,
        "user_name": user_name,
        "content": content,
        "ts": ts,
    }
    q["items"].append(item)
    q["next_id"] += 1
    return item, len(q["items"])


def _take(data: dict, guild_id, name, item_id, user_id):
    """拿走自己的那筆。

    回傳 (status, item)：
      'ok'        移除成功，item 是被移除的項目
      'empty'     queue 不存在或空
      'notfound'  該 id 不在 queue
      'forbidden' 該 id 屬於別人（item 是那筆，用來提示擁有者）
    """
    q = _get_queue(data, guild_id, name)
    if not q or not q["items"]:
        return "empty", None
    for i, it in enumerate(q["items"]):
        if it["id"] == item_id:
            if it["user_id"] != user_id:
                return "forbidden", it
            removed = q["items"].pop(i)
            _cleanup_if_empty(data, guild_id, name)
            return "ok", removed
    return "notfound", None


def _auto_summary(q: dict) -> str:
    """有 auto 設定時回傳一行摘要字串，否則回空字串。"""
    auto = q.get("auto")
    if not auto:
        return ""
    cooldown = auto.get("cooldown_days", DEFAULT_COOLDOWN_DAYS)
    nr = _parse_iso(auto.get("next_ready"))
    when = nr.strftime("%Y-%m-%d %H:%M") if nr else "立即"
    state = "開" if auto.get("enabled") else "關"
    cid = auto.get("channel_id")
    chan = f" · 頻道 <#{cid}>" if cid else ""
    return f"自動提醒：{state} · 冷卻 {cooldown} 天 · 下次可 pop：{when}{chan}"


def _pop(data: dict, guild_id, name):
    """移除隊頭（任何人都可以）。回傳被移除項目，空/不存在回 None。"""
    q = _get_queue(data, guild_id, name)
    if not q or not q["items"]:
        return None
    removed = q["items"].pop(0)
    _cleanup_if_empty(data, guild_id, name)
    return removed


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")


def _now_tz() -> datetime.datetime:
    return datetime.datetime.now(TZ)


def _parse_iso(ts: Optional[str]) -> Optional[datetime.datetime]:
    """解析 next_ready；None/壞值回 None（= 立即可 pop）。"""
    if not ts:
        return None
    try:
        dt = datetime.datetime.fromisoformat(ts)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=TZ)
        return dt
    except ValueError:
        return None


# ── Cog ──

class Queue(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lock = storage.lock_for(QUEUES_JSON)
        self.tick.start()

    def cog_unload(self):
        self.tick.cancel()

    group = app_commands.Group(name="queue", description="排隊系統", guild_only=True)

    # ── 冷卻期自動 pop 背景任務 ──

    @tasks.loop(seconds=60)
    async def tick(self):
        # 整圈持鎖，避免和指令的 read-modify-write 互踩（比照 scheduled.py）。
        async with self._lock:
            await self._fire_due()

    async def _fire_due(self):
        now = _now_tz()
        data = _load()
        dirty = False

        for guild_id_str, queues in list(data.items()):
            for name, q in list(queues.items()):
                auto = q.get("auto")
                if not auto or not auto.get("enabled"):
                    continue
                channel_id = auto.get("channel_id")
                if not channel_id:
                    continue
                if not q["items"]:
                    continue
                next_ready = _parse_iso(auto.get("next_ready"))
                if next_ready is not None and now < next_ready:
                    continue

                # 到期：pop 隊頭並 tag 邀請人。
                head = _pop(data, guild_id_str, name)
                if head is None:
                    continue

                cooldown = int(auto.get("cooldown_days", DEFAULT_COOLDOWN_DAYS))
                auto["next_ready"] = (now + datetime.timedelta(days=cooldown)).isoformat()
                dirty = True

                inviter = head["user_id"]
                try:
                    channel = self.bot.get_channel(int(channel_id)) or \
                        await self.bot.fetch_channel(int(channel_id))
                except Exception as e:
                    logger.warning("queue auto-pop: 取不到頻道 %s：%s", channel_id, e)
                    continue
                try:
                    await channel.send(
                        f"🔔 <@{inviter}> 冷卻期已滿，輪到你邀請的人了，請開投票！\n"
                        f"👤 {head['content']}",
                        allowed_mentions=discord.AllowedMentions(
                            everyone=False, roles=False,
                            users=[discord.Object(id=int(inviter))]),
                    )
                    logger.info(
                        "queue auto-pop: guild=%s queue=%s -> #%s tag=%s",
                        guild_id_str, name, getattr(channel, "name", channel_id), inviter,
                    )
                except discord.HTTPException as e:
                    logger.error("queue auto-pop send failed: %s", e)

        if dirty:
            _save(data)

    @tick.before_loop
    async def before_tick(self):
        await self.bot.wait_until_ready()

    # --- 共用 autocomplete 邏輯 ---

    def _name_choices(self, guild_id, current: str):
        data = _load()
        g = data.get(str(guild_id), {})
        cur = (current or "").lower()
        names = [n for n in g if cur in n.lower()]
        names.sort()
        return [app_commands.Choice(name=n, value=n) for n in names[:25]]

    def _own_item_choices(self, interaction: discord.Interaction, current: str):
        name = getattr(interaction.namespace, "name", None)
        if not name:
            return []
        data = _load()
        q = _get_queue(data, interaction.guild_id, name)
        if not q:
            return []
        cur = (current or "").strip()
        choices = []
        for it in q["items"]:
            if it["user_id"] != interaction.user.id:
                continue
            if cur and cur not in str(it["id"]):
                continue
            label = f"#{it['id']}｜{it['content']}"
            choices.append(app_commands.Choice(name=label[:100], value=it["id"]))
            if len(choices) >= 25:
                break
        return choices

    # --- add ---

    @group.command(name="add", description="把資訊排進 queue 隊尾")
    @app_commands.describe(name="queue 名稱（不存在會自動建立）", content="要排進去的內容")
    async def add(self, interaction: discord.Interaction, name: str, content: str):
        name = name.strip()
        content = content.strip()
        if not name:
            return await interaction.response.send_message("queue 名稱不可空白。", ephemeral=True)
        if len(name) > MAX_NAME:
            return await interaction.response.send_message(
                f"queue 名稱最長 {MAX_NAME} 字。", ephemeral=True)
        if not content:
            return await interaction.response.send_message("內容不可空白。", ephemeral=True)
        if len(content) > MAX_CONTENT:
            return await interaction.response.send_message(
                f"內容最長 {MAX_CONTENT} 字。", ephemeral=True)

        async with self._lock:
            data = _load()
            result = _enqueue(
                data, interaction.guild_id, name,
                interaction.user.id, interaction.user.display_name, content, _now(),
            )
            if result is None:
                return await interaction.response.send_message(
                    f"**{name}** 已滿（上限 {MAX_ITEMS} 筆）。", ephemeral=True)
            item, pos = result
            _save(data)

        await interaction.response.send_message(
            f"✅ 已排進 **{name}**，你在第 **{pos}** 位（id `{item['id']}`）：{content}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @add.autocomplete("name")
    async def _add_name_ac(self, interaction: discord.Interaction, current: str):
        return self._name_choices(interaction.guild_id, current)

    # --- list ---

    @group.command(name="list", description="列出某個 queue 的全部項目")
    @app_commands.describe(name="queue 名稱")
    async def list_(self, interaction: discord.Interaction, name: str):
        name = name.strip()
        data = _load()
        q = _get_queue(data, interaction.guild_id, name)
        if not q or not q["items"]:
            return await interaction.response.send_message(
                f"**{name}** 是空的或不存在。", ephemeral=True)

        lines = []
        for pos, it in enumerate(q["items"], start=1):
            head = "👑 " if pos == 1 else ""
            lines.append(f"{head}**{pos}.** `#{it['id']}` {it['user_name']}：{it['content']}")
        shown = lines[:25]
        body = "\n".join(shown)
        if len(lines) > 25:
            body += f"\n…還有 {len(lines) - 25} 筆"

        embed = discord.Embed(
            title=f"📋 {name}（{len(q['items'])} 人排隊）",
            description=body,
            color=discord.Color.blurple(),
        )
        auto_line = _auto_summary(q)
        if auto_line:
            embed.add_field(name="⏳ 自動投票提醒", value=auto_line, inline=False)
        await interaction.response.send_message(
            embed=embed, allowed_mentions=discord.AllowedMentions.none())

    @list_.autocomplete("name")
    async def _list_name_ac(self, interaction: discord.Interaction, current: str):
        return self._name_choices(interaction.guild_id, current)

    # --- top（peek，不移除） ---

    @group.command(name="top", description="看隊頭是誰，不移除")
    @app_commands.describe(name="queue 名稱")
    async def top(self, interaction: discord.Interaction, name: str):
        name = name.strip()
        data = _load()
        q = _get_queue(data, interaction.guild_id, name)
        if not q or not q["items"]:
            return await interaction.response.send_message(
                f"**{name}** 是空的或不存在。", ephemeral=True)
        head = q["items"][0]
        auto_line = _auto_summary(q)
        suffix = f"\n⏳ {auto_line}" if auto_line else ""
        await interaction.response.send_message(
            f"👑 **{name}** 隊頭：`#{head['id']}` {head['user_name']}：{head['content']}"
            f"（後面還有 {len(q['items']) - 1} 人）{suffix}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @top.autocomplete("name")
    async def _top_name_ac(self, interaction: discord.Interaction, current: str):
        return self._name_choices(interaction.guild_id, current)

    # --- queues（列出所有 queue） ---

    @group.command(name="queues", description="列出這個伺服器目前所有 queue")
    async def queues(self, interaction: discord.Interaction):
        data = _load()
        g = data.get(str(interaction.guild_id), {})
        if not g:
            return await interaction.response.send_message(
                "目前沒有任何 queue。用 `/queue add` 開一個吧。", ephemeral=True)
        lines = [f"• **{n}**（{len(q['items'])} 人）" for n, q in sorted(g.items())]
        embed = discord.Embed(
            title="🗂️ 目前的 queue",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed)

    # --- take（拿走自己的） ---

    @group.command(name="take", description="拿走自己排在 queue 裡的某一筆")
    @app_commands.describe(name="queue 名稱", id="要拿走的項目 id（打字會列出你自己的）")
    async def take(self, interaction: discord.Interaction, name: str, id: int):
        name = name.strip()
        async with self._lock:
            data = _load()
            status, item = _take(data, interaction.guild_id, name, id, interaction.user.id)
            if status == "ok":
                _save(data)

        if status == "ok":
            return await interaction.response.send_message(
                f"🗑️ 已從 **{name}** 拿走你的 `#{item['id']}`：{item['content']}",
                allowed_mentions=discord.AllowedMentions.none(),
            )
        if status == "empty":
            return await interaction.response.send_message(
                f"**{name}** 是空的或不存在。", ephemeral=True)
        if status == "forbidden":
            return await interaction.response.send_message(
                f"`#{id}` 是 {item['user_name']} 的，你只能拿走自己的資訊。", ephemeral=True)
        return await interaction.response.send_message(
            f"**{name}** 裡找不到 `#{id}`。", ephemeral=True)

    @take.autocomplete("name")
    async def _take_name_ac(self, interaction: discord.Interaction, current: str):
        return self._name_choices(interaction.guild_id, current)

    @take.autocomplete("id")
    async def _take_id_ac(self, interaction: discord.Interaction, current: str):
        return self._own_item_choices(interaction, current)

    # --- pop（移除隊頭，任何人） ---

    @group.command(name="pop", description="移除隊頭（最前面那筆），任何人都可以")
    @app_commands.describe(name="queue 名稱")
    async def pop(self, interaction: discord.Interaction, name: str):
        name = name.strip()
        cooldown_note = ""
        async with self._lock:
            data = _load()
            removed = _pop(data, interaction.guild_id, name)
            if removed is not None:
                # 手動 pop 一個自動 queue 時，也要重置冷卻，維持一致。
                q = _get_queue(data, interaction.guild_id, name)
                auto = q.get("auto") if q else None
                if auto and auto.get("enabled"):
                    cooldown = int(auto.get("cooldown_days", DEFAULT_COOLDOWN_DAYS))
                    nr = _now_tz() + datetime.timedelta(days=cooldown)
                    auto["next_ready"] = nr.isoformat()
                    cooldown_note = f"\n⏳ 冷卻 {cooldown} 天，下次可 pop：{nr.strftime('%Y-%m-%d %H:%M')}"
                _save(data)

        if removed is None:
            return await interaction.response.send_message(
                f"**{name}** 是空的或不存在。", ephemeral=True)
        await interaction.response.send_message(
            f"✅ 已處理 **{name}** 隊頭：`#{removed['id']}` "
            f"{removed['user_name']}：{removed['content']}{cooldown_note}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @pop.autocomplete("name")
    async def _pop_name_ac(self, interaction: discord.Interaction, current: str):
        return self._name_choices(interaction.guild_id, current)

    # --- clear（刪整個 queue，管理員/owner） ---

    @group.command(name="clear", description="刪掉整個 queue（限管理員）")
    @app_commands.describe(name="queue 名稱")
    async def clear(self, interaction: discord.Interaction, name: str):
        name = name.strip()
        is_owner = await self.bot.is_owner(interaction.user)
        perms = getattr(interaction.user, "guild_permissions", None)
        if not is_owner and not (perms and perms.manage_guild):
            return await interaction.response.send_message(
                "只有管理員（管理伺服器權限）或 bot owner 能清空 queue。", ephemeral=True)

        async with self._lock:
            data = _load()
            g = data.get(str(interaction.guild_id), {})
            if name not in g:
                return await interaction.response.send_message(
                    f"沒有叫 **{name}** 的 queue。", ephemeral=True)
            count = len(g[name]["items"])
            del g[name]
            if not g:
                data.pop(str(interaction.guild_id), None)
            _save(data)

        await interaction.response.send_message(f"🧹 已清空並刪除 **{name}**（{count} 筆）。")

    @clear.autocomplete("name")
    async def _clear_name_ac(self, interaction: discord.Interaction, current: str):
        return self._name_choices(interaction.guild_id, current)

    # --- 自動投票提醒（冷卻期 + 到期自動 pop + tag 邀請人） ---

    async def _require_manager(self, interaction: discord.Interaction) -> bool:
        is_owner = await self.bot.is_owner(interaction.user)
        perms = getattr(interaction.user, "guild_permissions", None)
        if is_owner or (perms and perms.manage_guild):
            return True
        await interaction.response.send_message(
            "只有管理員（管理伺服器權限）或 bot owner 能設定自動提醒。", ephemeral=True)
        return False

    @group.command(name="setup", description="開啟某 queue 的冷卻期自動投票提醒")
    @app_commands.describe(
        name="queue 名稱（不存在會自動建立）",
        cooldown_days=f"冷卻幾天（預設 {DEFAULT_COOLDOWN_DAYS}）",
        channel="提醒要發到哪個頻道（預設目前頻道）",
    )
    async def setup(self, interaction: discord.Interaction, name: str,
                    cooldown_days: Optional[int] = None,
                    channel: Optional[discord.TextChannel] = None):
        name = name.strip()
        if not name:
            return await interaction.response.send_message("queue 名稱不可空白。", ephemeral=True)
        if not await self._require_manager(interaction):
            return
        cooldown = DEFAULT_COOLDOWN_DAYS if cooldown_days is None else cooldown_days
        if cooldown < 0 or cooldown > 365:
            return await interaction.response.send_message(
                "冷卻天數請介於 0～365。", ephemeral=True)
        channel_id = (channel or interaction.channel).id

        async with self._lock:
            data = _load()
            g = data.setdefault(str(interaction.guild_id), {})
            q = g.get(name)
            if q is None:
                q = {"next_id": 1, "items": []}
                g[name] = q
            auto = q.setdefault("auto", {})
            auto["enabled"] = True
            auto["cooldown_days"] = cooldown
            auto["channel_id"] = channel_id
            auto.setdefault("next_ready", None)  # None = 第一個立即可 pop
            _save(data)

        await interaction.response.send_message(
            f"✅ **{name}** 已開啟自動投票提醒：冷卻 **{cooldown}** 天，"
            f"提醒發到 <#{channel_id}>。隊頭到期會自動 pop 並 tag 邀請人。\n"
            f"（要對齊已發生的投票，用 `/queue setnext` 設下次可 pop 日期）",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @setup.autocomplete("name")
    async def _setup_name_ac(self, interaction: discord.Interaction, current: str):
        return self._name_choices(interaction.guild_id, current)

    @group.command(name="setnext", description="手動設某 queue「下次可 pop 日期」")
    @app_commands.describe(name="queue 名稱", date="日期 YYYY-MM-DD（當天中午觸發）")
    async def setnext(self, interaction: discord.Interaction, name: str, date: str):
        name = name.strip()
        if not await self._require_manager(interaction):
            return
        try:
            d = datetime.date.fromisoformat(date.strip())
        except ValueError:
            return await interaction.response.send_message(
                "日期格式請用 `YYYY-MM-DD`，例如 `2026-07-06`。", ephemeral=True)
        nr = datetime.datetime(d.year, d.month, d.day, FIRE_HOUR, tzinfo=TZ)

        async with self._lock:
            data = _load()
            q = _get_queue(data, interaction.guild_id, name)
            if not q or not q.get("auto"):
                return await interaction.response.send_message(
                    f"**{name}** 還沒開啟自動提醒，先用 `/queue setup`。", ephemeral=True)
            q["auto"]["next_ready"] = nr.isoformat()
            _save(data)

        await interaction.response.send_message(
            f"✅ **{name}** 下次可 pop 日期設為 **{nr.strftime('%Y-%m-%d %H:%M')}**。",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @setnext.autocomplete("name")
    async def _setnext_name_ac(self, interaction: discord.Interaction, current: str):
        return self._name_choices(interaction.guild_id, current)

    @group.command(name="autooff", description="關閉某 queue 的自動投票提醒（變回純手動）")
    @app_commands.describe(name="queue 名稱")
    async def autooff(self, interaction: discord.Interaction, name: str):
        name = name.strip()
        if not await self._require_manager(interaction):
            return
        async with self._lock:
            data = _load()
            q = _get_queue(data, interaction.guild_id, name)
            if not q or not q.get("auto"):
                return await interaction.response.send_message(
                    f"**{name}** 沒有開啟自動提醒。", ephemeral=True)
            q.pop("auto", None)
            _cleanup_if_empty(data, interaction.guild_id, name)
            _save(data)

        await interaction.response.send_message(
            f"🛑 已關閉 **{name}** 的自動投票提醒，變回純手動 queue。",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @autooff.autocomplete("name")
    async def _autooff_name_ac(self, interaction: discord.Interaction, current: str):
        return self._name_choices(interaction.guild_id, current)

    # --- 統一錯誤處理 ---

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        logger.error("queue command error: %s", error)
        msg = f"發生錯誤：{error}"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Queue(bot))
