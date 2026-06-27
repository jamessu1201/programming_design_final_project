# -*- coding: utf-8 -*-
"""呼叫 OpenAI 相容端點的 LLM 功能。

- `/ask <問題> [圖片]`：一問一答，可附圖（多模態）。
- @機器人：在頻道 tag 機器人就會回，像聊天。
- 短期上下文：同一人在同一頻道的最近幾輪會帶進去（記憶體裡，不落地）。

API key 走專案慣例：環境變數 `llm_api_key` 優先，否則讀 `api_key/llm.txt`。
base_url / 模型名稱等非機密設定放 config.yaml 的 `llm:` 區塊。
"""
from __future__ import annotations

import collections
import datetime
import logging
import os
import re
from typing import Optional

import discord
import httpx
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

KEY_FILE = "api_key/llm.txt"
KEY_ENV = "llm_api_key"
DISCORD_LIMIT = 2000
IMAGE_TYPES = ("image/png", "image/jpeg", "image/gif", "image/webp")
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


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
        self.api_key = _load_key()
        if not self.api_key:
            logger.warning("LLM: no API key (set %s env or %s); commands will report unconfigured.",
                           KEY_ENV, KEY_FILE)
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(60.0))
        # (channel_id, user_id) -> deque[{"role","content","ts"}]
        self._mem: dict[tuple[int, int], collections.deque] = {}

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

    async def _answer(self, key, prompt: str, image_url: Optional[str]) -> str:
        """完整一輪：組訊息→呼叫→更新歷史。失敗丟例外給呼叫端處理。"""
        model = self.vision_model if image_url else self.text_model
        messages = self._build_messages(key, prompt, image_url)
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
            reply = await self._answer(key, 問題.strip(), image_url)
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

    # ── @機器人 觸發 ──

    @commands.Cog.listener("on_message")
    async def on_mention(self, message: discord.Message):
        if message.author.bot or not self.bot.user:
            return
        if self.bot.user not in message.mentions or message.mention_everyone:
            return
        if not self.api_key or not self.base_url:
            return
        # 去掉對機器人的 mention，留下實際問題。
        prompt = re.sub(rf"<@!?{self.bot.user.id}>", "", message.content).strip()
        image_url = self._first_image(message.attachments)
        if not prompt and not image_url:
            return await message.reply("你想問什麼？（也可以附一張圖）",
                                       allowed_mentions=discord.AllowedMentions.none())

        key = (message.channel.id, message.author.id)
        try:
            async with message.channel.typing():
                reply = await self._answer(key, prompt, image_url)
        except Exception as e:
            logger.error("LLM mention failed: %s", e)
            return await message.reply(f"呼叫 AI 失敗：{e}",
                                       allowed_mentions=discord.AllowedMentions.none())
        if not reply:
            return await message.reply("（AI 沒有回應內容）",
                                       allowed_mentions=discord.AllowedMentions.none())
        chunks = _split_chunks(reply)
        await message.reply(chunks[0], allowed_mentions=discord.AllowedMentions.none())
        for c in chunks[1:]:
            await message.channel.send(c, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot):
    await bot.add_cog(LLM(bot))
