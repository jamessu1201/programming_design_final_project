# -*- coding: utf-8 -*-
"""Per-guild scheduled text message CRUD (cron-based)."""
from __future__ import annotations

import json
import uuid
from pathlib import Path

from croniter import croniter
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import audit, security

router = APIRouter()

SCHEDULES_PATH = Path("json/scheduled_messages.json")


def _load() -> dict:
    if not SCHEDULES_PATH.exists():
        return {}
    try:
        with SCHEDULES_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    SCHEDULES_PATH.parent.mkdir(exist_ok=True)
    with SCHEDULES_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _hot_reload(bot) -> None:
    cog = bot.get_cog("Scheduled")
    if cog is not None and hasattr(cog, "reload_now"):
        cog.reload_now()


def _channel_name(bot, guild_id: int, channel_id: int) -> str:
    guild = bot.get_guild(guild_id)
    if guild is None:
        return f"#{channel_id}"
    ch = guild.get_channel(channel_id)
    return f"#{ch.name}" if ch else f"#{channel_id}"


def _is_text_entry(e: dict) -> bool:
    # Only expose plain-text entries; legacy built-in types stay invisible.
    t = e.get("type", "text")
    return t == "text"


@router.get("/guilds/{guild_id}/scheduled")
async def show(
    request: Request,
    guild_id: int,
    session: security.Session = Depends(security.require_guild_access),
):
    bot = request.app.state.bot
    guild = bot.get_guild(guild_id)
    entries = [e for e in _load().get(str(guild_id), []) if _is_text_entry(e)]
    enriched = [
        {**e, "channel_label": _channel_name(bot, guild_id, int(e["channel_id"]))}
        for e in entries
    ]
    return request.app.state.templates.TemplateResponse(
        request,
        "scheduled.html",
        {
            "session": session,
            "guild": {
                "id": guild_id,
                "name": guild.name if guild else "(unknown)",
                "icon": str(guild.icon.url) if guild and guild.icon else None,
            },
            "entries": enriched,
        },
    )


@router.post("/guilds/{guild_id}/scheduled/add")
async def add(
    request: Request,
    guild_id: int,
    channel_id: str = Form(...),
    message: str = Form(...),
    cron: str = Form(...),
    enabled: str = Form("on"),
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner and guild_id not in session.allowed_guilds:
        raise HTTPException(403, "no access to this guild")

    cron = cron.strip()
    if not croniter.is_valid(cron):
        raise HTTPException(400, f"無效的 cron 表達式: {cron}")
    try:
        cid = int(channel_id.strip())
    except ValueError:
        raise HTTPException(400, "channel_id 必須是數字")

    bot = request.app.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None or guild.get_channel(cid) is None:
        raise HTTPException(400, f"找不到頻道 {cid}")

    message = message.strip()
    if not message:
        raise HTTPException(400, "訊息不可為空")
    if len(message) > 1900:
        raise HTTPException(400, "訊息最長 1900 字")

    data = _load()
    bucket = data.setdefault(str(guild_id), [])
    new_entry = {
        "id": uuid.uuid4().hex[:12],
        "channel_id": str(cid),
        "type": "text",
        "message": message,
        "cron": cron,
        "enabled": (enabled == "on"),
        "last_fired": None,
    }
    bucket.append(new_entry)
    _save(data)
    _hot_reload(bot)
    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=guild_id,
        route="scheduled.add",
        action="add",
        after=new_entry,
    )
    return RedirectResponse(url=f"/guilds/{guild_id}/scheduled", status_code=303)


@router.post("/guilds/{guild_id}/scheduled/{entry_id}/toggle")
async def toggle(
    request: Request,
    guild_id: int,
    entry_id: str,
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner and guild_id not in session.allowed_guilds:
        raise HTTPException(403, "no access to this guild")

    data = _load()
    bucket = data.get(str(guild_id), [])
    for entry in bucket:
        if entry["id"] == entry_id and _is_text_entry(entry):
            before = entry["enabled"]
            entry["enabled"] = not before
            _save(data)
            _hot_reload(request.app.state.bot)
            audit.write_audit(
                user_id=session.user_id,
                username=session.username,
                guild_id=guild_id,
                route="scheduled.toggle",
                action="toggle",
                before=before,
                after=entry["enabled"],
            )
            break
    return RedirectResponse(url=f"/guilds/{guild_id}/scheduled", status_code=303)


@router.post("/guilds/{guild_id}/scheduled/{entry_id}/delete")
async def delete(
    request: Request,
    guild_id: int,
    entry_id: str,
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner and guild_id not in session.allowed_guilds:
        raise HTTPException(403, "no access to this guild")

    data = _load()
    bucket = data.get(str(guild_id), [])
    removed = None
    new_bucket = []
    for entry in bucket:
        if entry["id"] == entry_id and _is_text_entry(entry):
            removed = entry
        else:
            new_bucket.append(entry)
    if removed is None:
        return RedirectResponse(url=f"/guilds/{guild_id}/scheduled", status_code=303)
    if new_bucket:
        data[str(guild_id)] = new_bucket
    else:
        data.pop(str(guild_id), None)
    _save(data)
    _hot_reload(request.app.state.bot)
    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=guild_id,
        route="scheduled.delete",
        action="delete",
        before=removed,
    )
    return RedirectResponse(url=f"/guilds/{guild_id}/scheduled", status_code=303)
