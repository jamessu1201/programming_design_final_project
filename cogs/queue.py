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

import discord
from discord import app_commands
from discord.ext import commands

import storage

logger = logging.getLogger(__name__)

QUEUES_JSON = "json/queues.json"

MAX_NAME = 50
MAX_CONTENT = 500
MAX_ITEMS = 100  # 單一 queue 上限，防濫用


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


# ── Cog ──

class Queue(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lock = storage.lock_for(QUEUES_JSON)

    group = app_commands.Group(name="queue", description="排隊系統", guild_only=True)

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
        await interaction.response.send_message(
            f"👑 **{name}** 隊頭：`#{head['id']}` {head['user_name']}：{head['content']}"
            f"（後面還有 {len(q['items']) - 1} 人）",
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
        async with self._lock:
            data = _load()
            removed = _pop(data, interaction.guild_id, name)
            if removed is not None:
                _save(data)

        if removed is None:
            return await interaction.response.send_message(
                f"**{name}** 是空的或不存在。", ephemeral=True)
        await interaction.response.send_message(
            f"✅ 已處理 **{name}** 隊頭：`#{removed['id']}` "
            f"{removed['user_name']}：{removed['content']}",
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
