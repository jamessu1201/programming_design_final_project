# -*- coding: utf-8 -*-
"""呼叫 OpenAI 相容端點的 LLM 功能。

- `/ask <問題> [圖片]`：一問一答，可附圖（多模態）。
- @機器人：在頻道 tag 機器人就會回，像聊天。
- 短期上下文：同一人在同一頻道的最近幾輪會帶進去（記憶體裡，不落地）。

API key 走專案慣例：環境變數 `llm_api_key` 優先，否則讀 `api_key/llm.txt`。
base_url / 模型名稱等非機密設定放 config.yaml 的 `llm:` 區塊。
"""
from __future__ import annotations

import ast
import asyncio
import collections
import datetime
import json
import logging
import operator
import os
import re
import urllib.parse
from typing import Optional

import discord
import httpx
from bs4 import BeautifulSoup
from discord import app_commands
from discord.ext import commands

import storage

logger = logging.getLogger(__name__)

KEY_FILE = "api_key/llm.txt"
KEY_ENV = "llm_api_key"
DISCORD_LIMIT = 2000
IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
TZ = datetime.timezone(datetime.timedelta(hours=8))  # 台灣時間
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)

# 工具會讀到的既有資料檔（與對應 cog 同路徑）。
POINTS_JSON = "json/points.json"
QUEUES_JSON = "json/queues.json"
# 中央氣象署 36 小時預報（沿用 cogs/api.py 既有的 key；之後若換 key 一起改）。
CWB_KEY = "CWB-1461ABE2-E884-48EC-BBDE-F082E02B2D30"
CWB_URL = "https://opendata.cwb.gov.tw/api/v1/rest/datastore/F-C0032-001"
DDG_URL = "https://html.duckduckgo.com/html/"


# ── 給 LLM 用的工具（OpenAI function-calling schema） ──

TOOLS_SCHEMA = [
    {"type": "function", "function": {
        "name": "get_current_time",
        "description": "取得現在的台灣時間與日期。",
        "parameters": {"type": "object", "properties": {}},
    }},
    {"type": "function", "function": {
        "name": "calculate",
        "description": "計算一個算術運算式（+ - * / // % ** 與括號）。",
        "parameters": {"type": "object", "properties": {
            "expression": {"type": "string", "description": "例如 (3+4)*2"}},
            "required": ["expression"]},
    }},
    {"type": "function", "function": {
        "name": "get_weather",
        "description": "查台灣某縣市未來 36 小時天氣預報。",
        "parameters": {"type": "object", "properties": {
            "region": {"type": "string", "description": "完整縣市名，如『臺北市』『高雄市』"}},
            "required": ["region"]},
    }},
    {"type": "function", "function": {
        "name": "web_search",
        "description": "用 DuckDuckGo 搜尋即時網路資訊，回傳前幾筆標題/摘要/連結。",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string"},
            "num": {"type": "integer", "description": "幾筆，預設 5，最多 8"}},
            "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "get_points",
        "description": "查本伺服器的『屁眼點數』：不給 user 看排行榜，給 user 看某人點數。",
        "parameters": {"type": "object", "properties": {
            "user": {"type": "string", "description": "要查的人名（部分比對）；省略則回排行榜"},
            "top_n": {"type": "integer", "description": "排行榜取前幾名，預設 10"}},
        },
    }},
    {"type": "function", "function": {
        "name": "list_queue",
        "description": "查本伺服器的排隊 queue：不給 name 列出所有 queue，給 name 列出該 queue 的人。",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string", "description": "queue 名稱；省略則列出全部 queue"}},
        },
    }},
]

# 安全算術求值（不用 eval）。
_BIN_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
            ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY_OPS = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def _safe_eval(expr: str) -> str:
    def ev(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
            if isinstance(node.op, ast.Pow):
                r = ev(node.right)
                if abs(r) > 1000:
                    raise ValueError("指數太大")
                return operator.pow(ev(node.left), r)
            return _BIN_OPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
            return _UNARY_OPS[type(node.op)](ev(node.operand))
        raise ValueError("只支援數字與 + - * / // % ** 和括號")
    try:
        return str(ev(ast.parse(expr, mode="eval").body))
    except Exception as e:
        return f"無法計算「{expr}」：{e}"


def _load_key() -> Optional[str]:
    key = os.environ.get(KEY_ENV)
    if key:
        return key.strip()
    try:
        with open(KEY_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def _split_chunks(text: str, limit: int = DISCORD_LIMIT):
    """把長回覆切成 <=limit 的片段，盡量在換行處斷。"""
    text = text or ""
    chunks = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut])
        text = text[cut:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


class LLM(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        cfg = (getattr(bot, "config", None) or {}).get("llm", {}) or {}
        self.base_url = cfg.get("base_url", "").rstrip("/")
        self.text_model = cfg.get("text_model", "qwen3-30b")
        self.vision_model = cfg.get("vision_model", self.text_model)
        self.max_tokens = int(cfg.get("max_tokens", 1024))
        self.history_turns = int(cfg.get("history_turns", 6))
        self.history_ttl = datetime.timedelta(minutes=int(cfg.get("history_ttl_minutes", 30)))
        self.system_prompt = cfg.get("system_prompt", "")
        # 機器人互聊（bot ↔ bot）只開放在這個頻道，且要節流 + 上限防爆 token。
        self.botchat_channel = int(cfg.get("botchat_channel_id", 0)) or None
        self.botchat_delay = float(cfg.get("botchat_delay_seconds", 4))
        self.botchat_max_turns = int(cfg.get("botchat_max_turns", 40))
        self.tools_enabled = bool(cfg.get("tools_enabled", True))
        self.tool_max_rounds = int(cfg.get("tool_max_rounds", 5))
        self.api_key = _load_key()
        if not self.api_key:
            logger.warning("LLM: no API key (set %s env or %s); commands will report unconfigured.",
                           KEY_ENV, KEY_FILE)
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        # (channel_id, user_id) -> deque[{"role","content","ts"}]
        self._mem: dict[tuple[int, int], collections.deque] = {}
        # channel_id -> {"partner": int, "turns": int, "max": int}（進行中的機器人互聊）
        self._botchat: dict[int, dict] = {}

    def cog_unload(self):
        # 關掉 httpx client（背景排程關閉，不阻塞）。
        self.bot.loop.create_task(self._client.aclose())

    # ── 上下文記憶 ──

    def _now(self) -> datetime.datetime:
        return datetime.datetime.now(datetime.timezone.utc)

    def _recall(self, key) -> list[dict]:
        """取出未過期的歷史（只含 role/content）。"""
        dq = self._mem.get(key)
        if not dq:
            return []
        cutoff = self._now() - self.history_ttl
        while dq and dq[0]["ts"] < cutoff:
            dq.popleft()
        if not dq:
            self._mem.pop(key, None)
            return []
        return [{"role": m["role"], "content": m["content"]} for m in dq]

    def _remember(self, key, role: str, content: str):
        dq = self._mem.setdefault(key, collections.deque(maxlen=self.history_turns * 2))
        dq.append({"role": role, "content": content, "ts": self._now()})

    # ── 呼叫 LLM ──

    async def _chat(self, messages: list[dict], model: str) -> str:
        resp = await self._client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": model, "messages": messages, "max_tokens": self.max_tokens},
        )
        resp.raise_for_status()
        data = resp.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return _THINK_RE.sub("", content).strip()

    async def _chat_with_tools(self, messages: list[dict], model: str, ctx: dict) -> str:
        """tool-calling 迴圈：模型要工具 → 執行 → 回灌結果 → 再問，直到給出答案或到上限。"""
        for _ in range(self.tool_max_rounds):
            resp = await self._client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"model": model, "messages": messages, "max_tokens": self.max_tokens,
                      "tools": TOOLS_SCHEMA, "tool_choice": "auto"},
            )
            resp.raise_for_status()
            msg = (resp.json().get("choices") or [{}])[0].get("message", {})
            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                return _THINK_RE.sub("", msg.get("content") or "").strip()
            # 必須把帶 tool_calls 的 assistant 訊息原樣放回，下一輪才接得上。
            messages.append({"role": "assistant", "content": msg.get("content") or "",
                             "tool_calls": tool_calls})
            for tc in tool_calls:
                fn = tc.get("function", {})
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await self._dispatch_tool(fn.get("name", ""), args, ctx)
                messages.append({"role": "tool", "tool_call_id": tc.get("id"),
                                 "content": str(result)[:4000]})
        # 用完回合數還在要工具 → 最後一次不給 tools，逼它直接回答。
        return await self._chat(messages, model)

    async def _dispatch_tool(self, name: str, args: dict, ctx: dict) -> str:
        logger.info("LLM tool call: %s %s", name, args)
        try:
            if name == "get_current_time":
                return datetime.datetime.now(TZ).strftime("現在台灣時間：%Y-%m-%d %H:%M:%S")
            if name == "calculate":
                return _safe_eval(str(args.get("expression", "")))
            if name == "get_weather":
                return await self._tool_weather(str(args.get("region", "")))
            if name == "web_search":
                return await self._tool_search(str(args.get("query", "")), args.get("num", 5))
            if name == "get_points":
                return self._tool_points(ctx, args.get("user"), args.get("top_n", 10))
            if name == "list_queue":
                return self._tool_queue(ctx, args.get("name"))
            return f"未知工具：{name}"
        except Exception as e:
            logger.error("LLM tool %s failed: %s", name, e)
            return f"工具 {name} 執行失敗：{e}"

    async def _tool_weather(self, region: str) -> str:
        region = (region or "").strip()
        if not region:
            return "請提供完整縣市名稱（如『臺北市』）。"
        r = await self._client.get(CWB_URL, params={
            "Authorization": CWB_KEY, "format": "JSON", "locationName": region})
        r.raise_for_status()
        locs = r.json().get("records", {}).get("location", [])
        if not locs:
            return f"找不到「{region}」，縣市名要完整（如『臺北市』『新北市』）。"
        we = {e["elementName"]: e["time"] for e in locs[0]["weatherElement"]}
        wx, pop, mint, maxt = we.get("Wx", []), we.get("PoP", []), we.get("MinT", []), we.get("MaxT", [])
        lines = [f"{region} 未來 36 小時天氣："]
        for i in range(len(wx)):
            seg = wx[i]
            lines.append(
                f"・{seg['startTime'][5:16]}~{seg['endTime'][11:16]}："
                f"{seg['parameter']['parameterName']}，"
                f"降雨 {pop[i]['parameter']['parameterName']}%，"
                f"{mint[i]['parameter']['parameterName']}~{maxt[i]['parameter']['parameterName']}°C")
        return "\n".join(lines)

    async def _tool_search(self, query: str, num=5) -> str:
        query = (query or "").strip()
        if not query:
            return "請提供搜尋關鍵字。"
        try:
            num = max(1, min(int(num), 8))
        except (TypeError, ValueError):
            num = 5
        r = await self._client.post(
            DDG_URL, data={"q": query},
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        out = []
        for res in soup.select("div.result")[:num]:
            a = res.select_one("a.result__a")
            if not a:
                continue
            link = a.get("href", "")
            if link.startswith("//duckduckgo.com/l/"):
                q = urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("uddg")
                if q:
                    link = urllib.parse.unquote(q[0])
            snip = res.select_one(".result__snippet")
            snip = snip.get_text(" ", strip=True) if snip else ""
            out.append(f"- {a.get_text(strip=True)}\n  {snip}\n  {link}")
        if not out:
            return f"「{query}」沒有搜尋結果。"
        return f"「{query}」搜尋結果：\n" + "\n".join(out)

    def _tool_points(self, ctx: dict, user, top_n) -> str:
        g = storage.read_json(POINTS_JSON).get(str(ctx.get("guild_id")), {})
        if not g:
            return "這個伺服器還沒有點數資料。"
        ranked = sorted(g.values(), key=lambda r: r.get("points", 0), reverse=True)
        if user:
            u = str(user).strip().lower()
            for i, rec in enumerate(ranked, 1):
                if u in rec.get("name", "").lower():
                    return (f"{rec['name']}：{rec['points']} 點（第 {i} 名，"
                            f"訊息 {rec.get('messages', 0)} 則、語音 {rec.get('voice_min', 0)} 分）")
            return f"找不到名字含「{user}」的人。"
        try:
            n = max(1, min(int(top_n), 15))
        except (TypeError, ValueError):
            n = 10
        lines = [f"{i}. {r.get('name', '?')} — {r.get('points', 0)} 點"
                 for i, r in enumerate(ranked[:n], 1)]
        return "點數排行榜：\n" + "\n".join(lines)

    def _tool_queue(self, ctx: dict, name) -> str:
        g = storage.read_json(QUEUES_JSON).get(str(ctx.get("guild_id")), {})
        if not g:
            return "這個伺服器目前沒有任何 queue。"
        if name:
            q = g.get(str(name).strip())
            if not q:
                return f"沒有叫「{name}」的 queue。"
            items = q.get("items", [])
            if not items:
                return f"queue「{name}」是空的。"
            lines = [f"{i}. {it['user_name']}：{it['content']}" for i, it in enumerate(items, 1)]
            return f"queue「{name}」（{len(items)} 人）：\n" + "\n".join(lines)
        lines = [f"- {n}（{len(q.get('items', []))} 人）" for n, q in sorted(g.items())]
        return "目前的 queue：\n" + "\n".join(lines)

    def _build_messages(self, key, prompt: str, image_url: Optional[str]):
        """組出送給 API 的 messages，並回傳要存進歷史的純文字 user 內容。"""
        messages: list[dict] = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self._recall(key))
        if image_url:
            user_content = [
                {"type": "text", "text": prompt or "這張圖是什麼？"},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]
        else:
            user_content = prompt
        messages.append({"role": "user", "content": user_content})
        return messages

    async def _answer(self, key, prompt: str, image_url: Optional[str],
                      guild_id: Optional[int] = None) -> str:
        """完整一輪：組訊息→呼叫→更新歷史。失敗丟例外給呼叫端處理。"""
        model = self.vision_model if image_url else self.text_model
        messages = self._build_messages(key, prompt, image_url)
        # 有圖片時走純對話（vision 模型多半不支援 tools）；其餘可用工具。
        if self.tools_enabled and not image_url:
            ctx = {"guild_id": guild_id, "channel_id": key[0]}
            reply = await self._chat_with_tools(messages, model, ctx)
        else:
            reply = await self._chat(messages, model)
        # 歷史只存純文字（圖片 URL 會過期，且省 token）。
        self._remember(key, "user", prompt or "（圖片）")
        if reply:
            self._remember(key, "assistant", reply)
        return reply

    @staticmethod
    def _first_image(attachments) -> Optional[str]:
        for att in attachments:
            if (att.content_type or "") in IMAGE_TYPES:
                return att.url
        return None

    # ── /ask 指令 ──

    @app_commands.command(name="ask", description="問 AI（可附一張圖）")
    @app_commands.describe(問題="你想問的內容", 圖片="可選：附一張圖讓 AI 看")
    @app_commands.guild_only()
    async def ask(self, interaction: discord.Interaction, 問題: str,
                  圖片: Optional[discord.Attachment] = None):
        if not self.api_key or not self.base_url:
            return await interaction.response.send_message(
                "AI 還沒設定好（缺 API key 或 base_url）。", ephemeral=True)
        image_url = None
        if 圖片 is not None:
            if (圖片.content_type or "") not in IMAGE_TYPES:
                return await interaction.response.send_message(
                    "附件要是圖片（png/jpg/gif/webp）。", ephemeral=True)
            image_url = 圖片.url

        await interaction.response.defer(thinking=True)
        key = (interaction.channel_id, interaction.user.id)
        try:
            reply = await self._answer(key, 問題.strip(), image_url, guild_id=interaction.guild_id)
        except Exception as e:
            logger.error("LLM /ask failed: %s", e)
            return await interaction.followup.send(f"呼叫 AI 失敗：{e}")
        if not reply:
            return await interaction.followup.send("（AI 沒有回應內容）")
        chunks = _split_chunks(reply)
        await interaction.followup.send(chunks[0], allowed_mentions=discord.AllowedMentions.none())
        for c in chunks[1:]:
            await interaction.followup.send(c, allowed_mentions=discord.AllowedMentions.none())

    # ── 清除自己的上下文 ──

    @app_commands.command(name="forget", description="清除你在這個頻道的 AI 對話記憶")
    @app_commands.guild_only()
    async def forget(self, interaction: discord.Interaction):
        self._mem.pop((interaction.channel_id, interaction.user.id), None)
        await interaction.response.send_message("🧽 已清除你在這個頻道的對話記憶。", ephemeral=True)

    # ── 機器人互聊（只限定頻道、有節流與上限） ──

    @app_commands.command(name="botchat",
                          description="讓我跟另一隻機器人在指定頻道互相聊天（用 /stopchat 喊停）")
    @app_commands.describe(對象="要對聊的另一隻機器人", 開場="可選：開場白／聊天主題",
                           輪數="可選：最多回幾輪後自動停（防爆 token，預設看設定）")
    @app_commands.guild_only()
    async def botchat(self, interaction: discord.Interaction, 對象: discord.Member,
                      開場: Optional[str] = None, 輪數: Optional[int] = None):
        perms = getattr(interaction.user, "guild_permissions", None)
        is_owner = await self.bot.is_owner(interaction.user)
        if not is_owner and not (perms and perms.manage_guild):
            return await interaction.response.send_message(
                "只有管理員能開機器人對話（會一直呼叫 AI）。", ephemeral=True)
        if not self.api_key or not self.base_url:
            return await interaction.response.send_message("AI 還沒設定好。", ephemeral=True)
        if self.botchat_channel and interaction.channel_id != self.botchat_channel:
            return await interaction.response.send_message(
                f"機器人對話只能在 <#{self.botchat_channel}> 開。", ephemeral=True)
        if not 對象.bot:
            return await interaction.response.send_message("對象要選一隻機器人。", ephemeral=True)
        if 對象.id == self.bot.user.id:
            return await interaction.response.send_message("不能跟我自己聊…", ephemeral=True)

        max_turns = self.botchat_max_turns if 輪數 is None else max(1, min(輪數, 200))
        self._botchat[interaction.channel_id] = {"partner": 對象.id, "turns": 0, "max": max_turns}
        opening = (開場 or "嗨，我們來聊聊吧！").strip()
        await interaction.response.send_message(
            f"{對象.mention} {opening}",
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=[對象]),
        )

    @app_commands.command(name="stopchat", description="停止這個頻道的機器人互聊")
    @app_commands.guild_only()
    async def stopchat(self, interaction: discord.Interaction):
        # 任何人都能喊停（安全：誰都能拔插頭）。
        if self._botchat.pop(interaction.channel_id, None):
            await interaction.response.send_message("🛑 已停止這個頻道的機器人對話。")
        else:
            await interaction.response.send_message(
                "這個頻道沒有在進行機器人對話。", ephemeral=True)

    # ── @機器人 觸發 ──

    @commands.Cog.listener("on_message")
    async def on_mention(self, message: discord.Message):
        if not self.bot.user or message.author.id == self.bot.user.id:
            return  # 永不回自己（否則秒進無限自我迴圈）
        if self.bot.user not in message.mentions or message.mention_everyone:
            return
        if not self.api_key or not self.base_url:
            return

        is_bot = message.author.bot
        if is_bot:
            # 其他機器人：只有指定頻道開了 /botchat、且對到指定對象才回。
            session = self._botchat.get(message.channel.id)
            if not session or (session["partner"] and message.author.id != session["partner"]):
                return
            if session["turns"] >= session["max"]:
                self._botchat.pop(message.channel.id, None)
                return await message.channel.send(
                    f"🛑 機器人對話已達上限（{session['max']} 輪）自動停止。要再開用 `/botchat`。")
            session["turns"] += 1
            await asyncio.sleep(self.botchat_delay)  # 節流：別讓兩隻 bot 瞬間洗版／燒 token

        prompt = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()
        image_url = self._first_image(message.attachments)
        if not prompt and not image_url:
            if is_bot:
                return
            return await message.reply("你想問什麼？（也可以附一張圖）",
                                       allowed_mentions=discord.AllowedMentions.none())

        key = (message.channel.id, message.author.id)
        guild_id = message.guild.id if message.guild else None
        try:
            async with message.channel.typing():
                reply = await self._answer(key, prompt, image_url, guild_id=guild_id)
        except Exception as e:
            logger.error("LLM mention failed: %s", e)
            if is_bot:
                self._botchat.pop(message.channel.id, None)  # 出錯就停掉迴圈，別卡死
                return await message.channel.send(f"🛑 呼叫 AI 失敗，已停止機器人對話：{e}")
            return await message.reply(f"呼叫 AI 失敗：{e}",
                                       allowed_mentions=discord.AllowedMentions.none())
        if not reply:
            if is_bot:
                return
            return await message.reply("（AI 沒有回應內容）",
                                       allowed_mentions=discord.AllowedMentions.none())

        # 回給機器人時要 mention 對方，迴圈才接得下去；回人類則不 ping。
        if is_bot:
            am = discord.AllowedMentions(everyone=False, roles=False, users=[message.author])
        else:
            am = discord.AllowedMentions.none()
        chunks = _split_chunks(reply)
        await message.reply(chunks[0], mention_author=is_bot, allowed_mentions=am)
        for c in chunks[1:]:
            await message.channel.send(c, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot):
    await bot.add_cog(LLM(bot))
