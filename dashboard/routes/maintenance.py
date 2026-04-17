# -*- coding: utf-8 -*-
"""Owner-only maintenance dashboard: status + sync / reload / pull buttons."""
from __future__ import annotations

import datetime
import json
import logging
from pathlib import Path

import discord
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import audit, security
from .autodeploy import STATE_PATH as AUTODEPLOY_STATE_PATH

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/maintenance")


def _autodeploy_state() -> dict:
    if not AUTODEPLOY_STATE_PATH.exists():
        return {}
    try:
        with AUTODEPLOY_STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


@router.get("")
async def show(
    request: Request,
    session: security.Session = Depends(security.require_owner),
):
    bot = request.app.state.bot
    start = request.app.state.start_time
    uptime = datetime.datetime.now(datetime.timezone.utc) - start

    loaded_cogs = sorted(bot.extensions.keys())
    guild_count = len(bot.guilds)
    autodeploy = _autodeploy_state()

    autodeploy_channel = None
    if autodeploy.get("enabled") and autodeploy.get("channel_id"):
        ch = bot.get_channel(autodeploy["channel_id"])
        if ch:
            autodeploy_channel = {
                "id": ch.id,
                "name": ch.name,
                "guild": ch.guild.name if ch.guild else "?",
            }

    auto_cog = bot.get_cog("Auto")
    auto_tasks_state = {}
    if auto_cog is not None and hasattr(auto_cog, "_task_state"):
        auto_tasks_state = dict(auto_cog._task_state)

    return request.app.state.templates.TemplateResponse(
        request,
        "maintenance.html",
        {
            "session": session,
            "uptime_seconds": int(uptime.total_seconds()),
            "loaded_cogs": loaded_cogs,
            "guild_count": guild_count,
            "autodeploy": autodeploy,
            "autodeploy_channel": autodeploy_channel,
            "auto_tasks": auto_tasks_state,
        },
    )


@router.post("/sync")
async def sync_slash(
    request: Request,
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner:
        raise HTTPException(403, "owner only")

    bot = request.app.state.bot
    try:
        synced = await bot.tree.sync()
        result = f"全域同步 {len(synced)} 個 slash commands"
    except discord.HTTPException as e:
        result = f"同步失敗: {e}"
    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=None,
        route="maintenance.sync",
        action="sync_global",
        after=result,
    )
    return RedirectResponse(url=f"/maintenance?msg={result}", status_code=303)


@router.post("/reload")
async def reload_all(
    request: Request,
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner:
        raise HTTPException(403, "owner only")

    bot = request.app.state.bot
    success, failed = [], []
    for ext_name in list(bot.extensions):
        if ext_name == "cogs.dashboard":
            continue  # don't reload ourselves while serving this request
        try:
            await bot.reload_extension(ext_name)
            success.append(ext_name.replace("cogs.", ""))
        except Exception as e:
            failed.append(f"{ext_name}: {e}")
    result = f"reloaded {len(success)} cogs"
    if failed:
        result += f"; failed: {'; '.join(failed)}"
    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=None,
        route="maintenance.reload",
        action="reload_all",
        after={"success": success, "failed": failed},
    )
    return RedirectResponse(url=f"/maintenance?msg={result}", status_code=303)


@router.post("/deploy")
async def deploy(
    request: Request,
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner:
        raise HTTPException(403, "owner only")

    bot = request.app.state.bot
    admin = bot.get_cog("Admin")
    if admin is None:
        raise HTTPException(500, "Admin cog not loaded")

    try:
        result = await admin._pull_and_reload()
    except Exception as e:
        logger.exception("manual deploy failed")
        result = f"deploy failed: {e}"
    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=None,
        route="maintenance.deploy",
        action="git_pull_reload",
        after=str(result),
    )
    msg = result or "已是最新版本"
    return RedirectResponse(url=f"/maintenance?msg={msg[:200]}", status_code=303)
