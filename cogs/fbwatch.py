# -*- coding: utf-8 -*-
"""fb-watcher 關鍵字訂閱推播。

CT108 上的 `fb-watcher` 容器偵測到 FB 社團新貼文時，會用 Discord webhook 把貼文
推到群裡某個頻道（content=貼文內文、embed=標題/作者/圖片/permalink）。本 cog 讓
群裡成員各自用 `/fbwatch add` 訂閱關鍵字；當該頻道的 webhook 貼文命中某人的關鍵字
時，主動私訊 (DM) 通知他，DM 失敗（對方關閉伺服器成員私訊）才退而在頻道 @他。

- ephemeral 訊息只能在使用者觸發互動時回覆，無法主動推播 → 被動通知一律走 DM。
- 只比對「被 `/fbwatch setchannel` 綁定的頻道」裡 `webhook_id` 不為 None 的訊息，
  以免把該頻道的人類聊天也拿來比對。
"""
from __future__ import annotations

import logging
import os

import discord
import httpx
from discord import app_commands
from discord.ext import commands

import notify
import storage

logger = logging.getLogger(__name__)

FB_WATCH_JSON = "json/fb_watch.json"
MAX_KEYWORDS = 25          # 每人關鍵字數量上限
MAX_KEYWORD_LEN = 100      # 單一關鍵字長度上限
SNIPPET_LEN = 500          # DM 內貼文節錄長度上限


# ── 持久化 ──

def _load() -> dict:
    return _normalize(storage.read_json(FB_WATCH_JSON, default={}))


def _save(data: dict) -> None:
    storage.write_json_atomic(FB_WATCH_JSON, data)


def _normalize(data) -> dict:
    """確保結構為 {"channel_id": int|None, "subscriptions": {uid: [kw,...]}}。"""
    if not isinstance(data, dict):
        data = {}
    data.setdefault("channel_id", None)
    subs = data.get("subscriptions")
    if not isinstance(subs, dict):
        subs = {}
    data["subscriptions"] = subs
    return data


# ── 比對（純函式，方便測試） ──

def _haystack(message: discord.Message) -> str:
    """把貼文內文 + embed 標題/作者組成可比對的小寫字串。"""
    parts = [message.content or ""]
    for e in message.embeds:
        if e.title:
            parts.append(e.title)
        if e.author and e.author.name:
            parts.append(e.author.name)
    return "\n".join(parts).lower()


def _match(subs: dict, haystack_low: str) -> dict:
    """回傳 {uid: [命中的關鍵字, ...]}，只含至少命中一個的人。"""
    matched = {}
    for uid, kws in subs.items():
        hits = [k for k in kws if k in haystack_low]
        if hits:
            matched[uid] = hits
    return matched


# ── ntfy 設定 ──

NTFY_TOKEN_ENV = "ntfy_token"
NTFY_TOKEN_FILE = "api_key/ntfy.txt"


def _load_ntfy_token() -> str | None:
    """ntfy auth token：環境變數優先，否則讀 api_key/ntfy.txt（仿 cogs/llm.py:_load_key）。"""
    tok = os.environ.get(NTFY_TOKEN_ENV)
    if tok:
        return tok.strip()
    try:
        with open(NTFY_TOKEN_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


# ── Cog ──

class FbWatch(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._lock = storage.lock_for(FB_WATCH_JSON)
        # 只有本 cog 會寫這個檔，記憶體快取一份避免每則訊息都讀檔。
        self.data = _load()

        # ntfy 手機推播設定（config.yaml 的 ntfy: 區塊）。沒設就只發 DM。
        cfg = (getattr(bot, "config", None) or {}).get("ntfy", {}) or {}
        self.ntfy_base = (cfg.get("base_url") or "").rstrip("/")
        self.ntfy_topics = {str(k): v for k, v in (cfg.get("user_topics") or {}).items()}
        self.ntfy_priority = cfg.get("priority") or None
        self.ntfy_token = _load_ntfy_token()
        # 重用一個 client，避免每則貼文都開新連線。
        self._http = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))

    def cog_unload(self):
        # 關掉 httpx client（背景排程關閉，不阻塞）。
        self.bot.loop.create_task(self._http.aclose())

    # --- slash 指令 ---

    group = app_commands.Group(
        name="fbwatch", description="fb-watcher 關鍵字訂閱", guild_only=True)

    @group.command(name="add", description="新增一個要訂閱的關鍵字（命中 fb-watcher 貼文時私訊你）")
    @app_commands.describe(keyword="想要被通知的關鍵字（不分大小寫）")
    async def add(self, interaction: discord.Interaction, keyword: str):
        kw = keyword.strip().lower()
        if not kw:
            return await interaction.response.send_message(
                "關鍵字不能是空白。", ephemeral=True)
        if len(kw) > MAX_KEYWORD_LEN:
            return await interaction.response.send_message(
                f"關鍵字太長（上限 {MAX_KEYWORD_LEN} 字）。", ephemeral=True)

        uid = str(interaction.user.id)
        async with self._lock:
            data = _load()
            subs = data["subscriptions"].setdefault(uid, [])
            if kw in subs:
                msg = f"你已經訂閱過「{kw}」了。"
            elif len(subs) >= MAX_KEYWORDS:
                msg = f"關鍵字數量已達上限（{MAX_KEYWORDS} 個），請先用 `/fbwatch remove` 移除一些。"
            else:
                subs.append(kw)
                _save(data)
                self.data = data
                msg = f"✅ 已訂閱關鍵字「{kw}」。命中 fb-watcher 貼文時我會私訊你。"
        await interaction.response.send_message(msg, ephemeral=True)

    @group.command(name="remove", description="移除一個已訂閱的關鍵字")
    @app_commands.describe(keyword="要移除的關鍵字")
    async def remove(self, interaction: discord.Interaction, keyword: str):
        kw = keyword.strip().lower()
        uid = str(interaction.user.id)
        async with self._lock:
            data = _load()
            subs = data["subscriptions"].get(uid, [])
            if kw not in subs:
                msg = f"你沒有訂閱「{kw}」。"
            else:
                subs.remove(kw)
                if not subs:
                    data["subscriptions"].pop(uid, None)
                _save(data)
                self.data = data
                msg = f"🗑️ 已移除關鍵字「{kw}」。"
        await interaction.response.send_message(msg, ephemeral=True)

    @group.command(name="list", description="列出你訂閱的所有關鍵字")
    async def list_(self, interaction: discord.Interaction):
        subs = _load()["subscriptions"].get(str(interaction.user.id), [])
        if not subs:
            return await interaction.response.send_message(
                "你目前沒有訂閱任何關鍵字。用 `/fbwatch add` 新增。", ephemeral=True)
        body = "\n".join(f"・{k}" for k in subs)
        await interaction.response.send_message(
            f"你訂閱的關鍵字（{len(subs)} 個）：\n{body}", ephemeral=True)

    @group.command(name="setchannel",
                   description="把目前頻道設為 fb-watcher 推播來源（需管理伺服器權限）")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def setchannel(self, interaction: discord.Interaction):
        async with self._lock:
            data = _load()
            data["channel_id"] = interaction.channel_id
            _save(data)
            self.data = data
        await interaction.response.send_message(
            f"✅ 已把 <#{interaction.channel_id}> 設為 fb-watcher 推播來源頻道。"
            f"之後這個頻道的貼文命中誰的關鍵字，我就會私訊那個人。", ephemeral=True)

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "只有具備「管理伺服器」權限的人能設定頻道。"
        else:
            logger.error("fbwatch command error: %s", error)
            msg = f"發生錯誤：{error}"
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    # --- 監聽 fb-watcher 貼文 → 推播 ---

    def _build_dm(self, message: discord.Message, hits: list, permalink) -> str:
        kw_str = "、".join(hits)
        lines = [f"🔔 fb-watcher 有新貼文命中你的關鍵字：**{kw_str}**"]
        snippet = (message.content or "").strip()
        if snippet:
            if len(snippet) > SNIPPET_LEN:
                snippet = snippet[:SNIPPET_LEN - 1] + "…"
            lines += ["", snippet]
        lines += ["", f"🔗 Discord 訊息：{message.jump_url}"]
        if permalink:
            lines.append(f"📘 原貼文：{permalink}")
        return "\n".join(lines)

    async def _push_ntfy(self, uid: str, message: discord.Message, hits: list, permalink) -> None:
        """命中關鍵字時，對有設定 topic 的人推 ntfy 到手機。沒設就跳過。"""
        topic = self.ntfy_topics.get(uid)
        if not topic or not self.ntfy_base:
            return
        await notify.push(
            f"{self.ntfy_base}/{topic}",
            self._build_dm(message, hits, permalink),
            title="fb-watcher alert",          # ASCII（避免中文 header）
            tags="bell",
            priority=self.ntfy_priority,
            click=permalink or message.jump_url,
            client=self._http,
            token=self.ntfy_token,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        channel_id = self.data.get("channel_id")
        # 只處理被綁定頻道裡、由 webhook（fb-watcher）發出的訊息
        if channel_id is None or message.channel.id != channel_id:
            return
        if message.webhook_id is None or message.guild is None:
            return

        subs = self.data.get("subscriptions") or {}
        if not subs:
            return

        matched = _match(subs, _haystack(message))
        if not matched:
            return

        permalink = next((e.url for e in message.embeds if e.url), None)
        failed = []  # DM 不出去的人，最後在頻道 @他 當備援
        for uid, hits in matched.items():
            member = message.guild.get_member(int(uid))
            if member is None:
                continue  # 已退群
            try:
                await member.send(self._build_dm(message, hits, permalink))
            except discord.Forbidden:
                failed.append(uid)
            except discord.HTTPException:
                logger.exception("fbwatch: 私訊 %s 失敗", uid)
            # DM 之外，若該人有設 ntfy topic，再推一份到手機（DM 成敗都推、best-effort）。
            await self._push_ntfy(uid, message, hits, permalink)

        if failed:
            mentions = " ".join(f"<@{u}>" for u in failed)
            await message.channel.send(
                f"{mentions} 🔔 這則貼文命中你訂閱的關鍵字（你的私訊關閉了，改在這裡通知）。",
                allowed_mentions=discord.AllowedMentions(
                    everyone=False, roles=False,
                    users=[discord.Object(id=int(u)) for u in failed]),
            )


async def setup(bot):
    await bot.add_cog(FbWatch(bot))
