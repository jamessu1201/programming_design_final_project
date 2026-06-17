# -*- coding: utf-8 -*-
"""屁眼點數排行榜（限特定伺服器）。看：能管理該 guild 的人；reset：只有 owner。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

import storage

from .. import audit, security
from cogs.points import TARGET_GUILD

router = APIRouter()

POINTS_PATH = Path("json/points.json")


def _load() -> dict:
    return storage.read_json(POINTS_PATH)


def _save(data: dict) -> None:
    storage.write_json_atomic(POINTS_PATH, data)


def _resolve_name(bot, guild, uid: str, rec: dict) -> str:
    """即時抓現在的帳號名；查不到才退回存檔的名字。"""
    try:
        uid_int = int(uid)
    except (TypeError, ValueError):
        return rec.get("name", str(uid))
    member = guild.get_member(uid_int) if guild else None
    if member is not None:
        return member.display_name
    user = bot.get_user(uid_int)
    if user is not None:
        return user.name
    return rec.get("name", str(uid))


@router.get("/guilds/{guild_id}/points")
async def leaderboard(
    request: Request,
    guild_id: int,
    session: security.Session = Depends(security.require_guild_access),
):
    bot = request.app.state.bot
    guild = bot.get_guild(guild_id)
    rows = []
    if guild_id == TARGET_GUILD:
        g = _load().get(str(guild_id), {})
        board = sorted(g.items(), key=lambda kv: kv[1]["points"], reverse=True)
        for rank, (uid, rec) in enumerate(board, start=1):
            rows.append({
                "rank": rank,
                "user_id": uid,
                "name": _resolve_name(bot, guild, uid, rec),
                "points": rec.get("points", 0),
                "voice_min": rec.get("voice_min", 0),
                "messages": rec.get("messages", 0),
            })
    return request.app.state.templates.TemplateResponse(
        request,
        "points.html",
        {
            "session": session,
            "guild": {
                "id": guild_id,
                "name": guild.name if guild else "(unknown)",
                "icon": str(guild.icon.url) if guild and guild.icon else None,
            },
            "is_target": guild_id == TARGET_GUILD,
            "rows": rows,
        },
    )


@router.post("/guilds/{guild_id}/points/reset")
async def reset(
    request: Request,
    guild_id: int,
    user_id: Optional[str] = Form(None),
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner:
        raise HTTPException(403, "owner only")

    async with storage.lock_for(POINTS_PATH):
        data = _load()
        g = data.get(str(guild_id), {})
        before = len(g)
        if user_id:
            if str(user_id) in g:
                del g[str(user_id)]
                if not g:
                    data.pop(str(guild_id), None)
                _save(data)
            action = "reset_user"
            after = {"removed_user": user_id}
        else:
            data.pop(str(guild_id), None)
            _save(data)
            action = "reset_all"
            after = {"cleared": before}

    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=guild_id,
        route="points.reset",
        action=action,
        before={"count": before},
        after=after,
    )
    return RedirectResponse(url=f"/guilds/{guild_id}/points", status_code=303)
