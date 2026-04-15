# -*- coding: utf-8 -*-
"""Per-guild prefix setting (mirrors cogs/others.py rules)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import audit, security

router = APIRouter()

PREFIX_PATH = Path("json/prefix.json")
DEFAULT_PREFIX = "!"
MAX_PREFIX_LEN = 20


def _load() -> dict:
    if not PREFIX_PATH.exists():
        return {}
    try:
        with PREFIX_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    PREFIX_PATH.parent.mkdir(exist_ok=True)
    with PREFIX_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


@router.get("/guilds/{guild_id}/prefix")
async def show(
    request: Request,
    guild_id: int,
    session: security.Session = Depends(security.require_guild_access),
):
    bot = request.app.state.bot
    guild = bot.get_guild(guild_id)
    current = _load().get(str(guild_id), DEFAULT_PREFIX)
    return request.app.state.templates.TemplateResponse(
        request,
        "prefix.html",
        {
            "session": session,
            "guild": {
                "id": guild_id,
                "name": guild.name if guild else "(unknown)",
                "icon": str(guild.icon.url) if guild and guild.icon else None,
            },
            "current": current,
            "default": DEFAULT_PREFIX,
            "max_len": MAX_PREFIX_LEN,
        },
    )


@router.post("/guilds/{guild_id}/prefix")
async def set_prefix(
    request: Request,
    guild_id: int,
    new_prefix: str = Form(...),
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner and guild_id not in session.allowed_guilds:
        raise HTTPException(403, "no access to this guild")

    new_prefix = new_prefix.strip()
    if not new_prefix:
        raise HTTPException(400, "prefix 不可為空")
    if len(new_prefix) > MAX_PREFIX_LEN:
        raise HTTPException(400, f"prefix 最長 {MAX_PREFIX_LEN} 字元")
    if any(c.isspace() for c in new_prefix):
        raise HTTPException(400, "prefix 不可包含空白")

    data = _load()
    before = data.get(str(guild_id), DEFAULT_PREFIX)
    data[str(guild_id)] = new_prefix
    _save(data)
    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=guild_id,
        route="prefix.set",
        action="set",
        before=before,
        after=new_prefix,
    )
    return RedirectResponse(url=f"/guilds/{guild_id}/prefix", status_code=303)
