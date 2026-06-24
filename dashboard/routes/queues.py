# -*- coding: utf-8 -*-
"""Per-guild queue viewer (read-only). 操作仍在 Discord 用 /queue。"""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Request

from .. import security

router = APIRouter(prefix="/guilds/{guild_id}/queues", tags=["queues"])

QUEUES_PATH = Path("json/queues.json")


def _load() -> dict:
    if not QUEUES_PATH.exists():
        return {}
    try:
        with QUEUES_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


@router.get("")
async def list_queues(
    request: Request,
    guild_id: int,
    session: security.Session = Depends(security.require_guild_access),
):
    bot = request.app.state.bot
    guild = bot.get_guild(guild_id)
    g = _load().get(str(guild_id), {})
    queues = []
    for name, q in sorted(g.items()):
        auto = q.get("auto")
        auto_view = None
        if auto:
            cid = auto.get("channel_id")
            chan = bot.get_channel(int(cid)) if cid else None
            next_ready = auto.get("next_ready")
            auto_view = {
                "enabled": auto.get("enabled", False),
                "cooldown_days": auto.get("cooldown_days", 30),
                "channel_name": f"#{chan.name}" if chan else (f"#{cid}" if cid else "—"),
                "next_ready": next_ready.replace("T", " ")[:16] if next_ready else "立即",
            }
        queues.append({"name": name, "items": q.get("items", []), "auto": auto_view})
    return request.app.state.templates.TemplateResponse(
        request,
        "queues.html",
        {
            "session": session,
            "guild": {
                "id": guild_id,
                "name": guild.name if guild else "(unknown)",
                "icon": str(guild.icon.url) if guild and guild.icon else None,
            },
            "queues": queues,
        },
    )
