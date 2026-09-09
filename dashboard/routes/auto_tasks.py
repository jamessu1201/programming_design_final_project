# -*- coding: utf-8 -*-
"""Owner-only toggle for built-in scheduled tasks in cogs/auto.py."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import audit, security

router = APIRouter(prefix="/maintenance/auto-tasks")

ALLOWED = {"leetcode", "happy_birthday", "lol_reminder", "contest_check"}


@router.post("/{name}/toggle")
async def toggle(
    request: Request,
    name: str,
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner:
        raise HTTPException(403, "owner only")
    if name not in ALLOWED:
        raise HTTPException(400, f"unknown task: {name}")

    bot = request.app.state.bot
    cog = bot.get_cog("Auto")
    if cog is None:
        raise HTTPException(500, "Auto cog not loaded")

    before = cog.is_task_enabled(name)
    cog.set_task_enabled(name, not before)
    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=None,
        route="maintenance.auto_tasks.toggle",
        action="toggle",
        before={name: before},
        after={name: not before},
    )
    return RedirectResponse(url="/maintenance", status_code=303)
