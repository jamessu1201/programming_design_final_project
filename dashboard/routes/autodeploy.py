# -*- coding: utf-8 -*-
"""Toggle the autodeploy state from the dashboard (owner-only)."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import audit, security

router = APIRouter(prefix="/maintenance/autodeploy")

STATE_PATH = Path("json/autodeploy.json")


def _load() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(state: dict) -> None:
    STATE_PATH.parent.mkdir(exist_ok=True)
    with STATE_PATH.open("w", encoding="utf-8") as f:
        json.dump(state, f)


@router.post("/on")
async def turn_on(
    request: Request,
    channel_id: int = Form(...),
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner:
        raise HTTPException(403, "owner only")

    bot = request.app.state.bot
    channel = bot.get_channel(channel_id)
    if channel is None:
        try:
            channel = await bot.fetch_channel(channel_id)
        except Exception as e:
            raise HTTPException(400, f"找不到頻道 {channel_id}: {e}")

    before = _load()
    new_state = {"enabled": True, "channel_id": channel_id}
    _save(new_state)

    admin_cog = bot.get_cog("Admin")
    if admin_cog is not None:
        admin_cog._deploy_channel = channel
        admin_cog._auto_deploy = True
        if not admin_cog.git_poll.is_running():
            admin_cog.git_poll.start()

    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=None,
        route="maintenance.autodeploy",
        action="on",
        before=before,
        after=new_state,
    )
    return RedirectResponse(url="/maintenance", status_code=303)


@router.post("/off")
async def turn_off(
    request: Request,
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner:
        raise HTTPException(403, "owner only")

    before = _load()
    _save({"enabled": False})

    bot = request.app.state.bot
    admin_cog = bot.get_cog("Admin")
    if admin_cog is not None and admin_cog.git_poll.is_running():
        admin_cog.git_poll.cancel()
        admin_cog._auto_deploy = False

    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=None,
        route="maintenance.autodeploy",
        action="off",
        before=before,
        after={"enabled": False},
    )
    return RedirectResponse(url="/maintenance", status_code=303)
