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
    queues = [
        {"name": name, "items": q.get("items", [])}
        for name, q in sorted(g.items())
    ]
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
