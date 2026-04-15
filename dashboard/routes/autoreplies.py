# -*- coding: utf-8 -*-
"""Autoreply config (per-guild on/off + global trigger list)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import audit, security

router = APIRouter()

REPLIES_PATH = Path("json/auto_replies.json")
STATE_PATH = Path("json/replies_state.json")


def _load_replies() -> list:
    if not REPLIES_PATH.exists():
        return []
    try:
        with REPLIES_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def _save_replies(data: list) -> None:
    REPLIES_PATH.parent.mkdir(exist_ok=True)
    with REPLIES_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False)


async def _hot_reload_event_cog(bot) -> None:
    cog = bot.get_cog("Event")
    if cog is None:
        return
    if hasattr(cog, "reload_replies_now"):
        await cog.reload_replies_now()
    else:
        # fallback: poke the in-memory caches directly
        cog.auto_replies = _load_replies()
        cog.replies_enabled = _load_state()


@router.get("/guilds/{guild_id}/autoreplies")
async def show(
    request: Request,
    guild_id: int,
    session: security.Session = Depends(security.require_guild_access),
):
    bot = request.app.state.bot
    guild = bot.get_guild(guild_id)
    state = _load_state()
    enabled = state.get(str(guild_id), True)
    replies = _load_replies()
    return request.app.state.templates.TemplateResponse(
        request,
        "autoreplies.html",
        {
            "session": session,
            "guild": {
                "id": guild_id,
                "name": guild.name if guild else "(unknown)",
                "icon": str(guild.icon.url) if guild and guild.icon else None,
            },
            "enabled": enabled,
            "replies": replies,
        },
    )


@router.post("/guilds/{guild_id}/autoreplies/toggle")
async def toggle(
    request: Request,
    guild_id: int,
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner and guild_id not in session.allowed_guilds:
        raise HTTPException(403, "no access to this guild")

    state = _load_state()
    before = state.get(str(guild_id), True)
    state[str(guild_id)] = not before
    _save_state(state)
    await _hot_reload_event_cog(request.app.state.bot)
    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=guild_id,
        route="autoreplies.toggle",
        action="toggle",
        before=before,
        after=state[str(guild_id)],
    )
    return RedirectResponse(url=f"/guilds/{guild_id}/autoreplies", status_code=303)


@router.post("/autoreplies/add")
async def add_entry(
    request: Request,
    triggers: str = Form(...),
    urls: str = Form(...),
    redirect_to: str = Form("/"),
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner:
        raise HTTPException(403, "owner only")

    trigger_list = [t.strip() for t in triggers.split(",") if t.strip()]
    url_list = [u.strip() for u in urls.splitlines() if u.strip()]
    if not trigger_list:
        raise HTTPException(400, "至少要 1 個 trigger")
    if not url_list:
        raise HTTPException(400, "至少要 1 個 URL")

    data = _load_replies()
    before = list(data)
    data.append({"triggers": trigger_list, "urls": url_list})
    _save_replies(data)
    await _hot_reload_event_cog(request.app.state.bot)
    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=None,
        route="autoreplies.add",
        action="add",
        before=before,
        after=data,
    )
    return RedirectResponse(url=redirect_to, status_code=303)


@router.post("/autoreplies/delete")
async def delete_entry(
    request: Request,
    index: int = Form(...),
    redirect_to: str = Form("/"),
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner:
        raise HTTPException(403, "owner only")

    data = _load_replies()
    if not 0 <= index < len(data):
        raise HTTPException(400, "bad index")
    before = list(data)
    removed = data.pop(index)
    _save_replies(data)
    await _hot_reload_event_cog(request.app.state.bot)
    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=None,
        route="autoreplies.delete",
        action="delete",
        before=before,
        after={"removed": removed, "remaining": data},
    )
    return RedirectResponse(url=redirect_to, status_code=303)
