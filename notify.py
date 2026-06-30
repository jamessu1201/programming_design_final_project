# -*- coding: utf-8 -*-
"""ntfy 手機推播 helper（async）。

仿 moneybank/services/notifier.py，但因為呼叫端（fbwatch 的 on_message）是 async，
改用 httpx.AsyncClient，避免在 event loop 裡用同步 requests 阻塞。

設計重點（沿用 moneybank 眉角）：
- topic_url = 完整 topic 網址（base_url + "/" + topic），POST body 就是訊息內文。
- ntfy 的 HTTP header 必須是 ASCII；中文 Title 會在 httpx build_request 階段就丟
  UnicodeEncodeError → 自動把標題折進 body 第一行、header 改用固定 ASCII。
- best-effort：任何失敗只記 log、回傳 False，絕不往上拋（推播是副作用，不能炸主流程）。
- 未設定 topic_url → 靜默 return False。
"""
from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


async def push(
    topic_url: str,
    message: str,
    *,
    title: str = "dcbot",
    tags: str = "bell",
    priority: str | None = None,
    click: str | None = None,
    client: httpx.AsyncClient | None = None,
    token: str | None = None,
) -> bool:
    """發 ntfy 通知。回傳是否送出。未設 topic_url 則靜默略過。"""
    url = (topic_url or "").strip()
    if not url:
        return False

    # ntfy header 必須 ASCII；中文 title 折進內文、header 改用 ASCII 後備。
    try:
        title.encode("ascii")
        safe_title = title
    except UnicodeEncodeError:
        message = f"{title}\n{message}"
        safe_title = "dcbot"

    headers = {"Title": safe_title, "Tags": tags}
    if priority:
        headers["Priority"] = priority      # high/urgent…（ASCII，安全）
    if click:
        headers["Click"] = click            # 點通知開的網址（permalink / jump_url）
    if token:
        headers["Authorization"] = f"Bearer {token}"

    owns_client = client is None
    if owns_client:
        client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
    try:
        r = await client.post(url, content=message.encode("utf-8"), headers=headers)
        r.raise_for_status()
        return True
    except Exception:
        logger.exception("[ntfy] 推播失敗")
        return False
    finally:
        if owns_client:
            await client.aclose()
