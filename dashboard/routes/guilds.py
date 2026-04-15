# -*- coding: utf-8 -*-
"""Top-level guild selector + per-guild overview."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from .. import security

router = APIRouter()


def _list_visible_guilds(session: security.Session, bot) -> list[dict]:
    guilds = []
    for g in bot.guilds:
        if not session.is_owner and g.id not in session.allowed_guilds:
            continue
        guilds.append({
            "id": g.id,
            "name": g.name,
            "icon": str(g.icon.url) if g.icon else None,
            "member_count": g.member_count,
        })
    guilds.sort(key=lambda x: x["name"].lower())
    return guilds


@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    session = security.load_session(request)
    templates = request.app.state.templates
    if session is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"oauth_login_url": "/auth/login"},
        )
    bot = request.app.state.bot
    guilds = _list_visible_guilds(session, bot)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "session": session,
            "guilds": guilds,
        },
    )


@router.get("/guilds/{guild_id}", response_class=HTMLResponse)
async def guild_overview(
    request: Request,
    guild_id: int,
    session: security.Session = Depends(security.require_guild_access),
):
    bot = request.app.state.bot
    guild = bot.get_guild(guild_id)
    if guild is None:
        return RedirectResponse(url="/", status_code=302)
    return request.app.state.templates.TemplateResponse(
        request,
        "guild.html",
        {
            "session": session,
            "guild": {
                "id": guild.id,
                "name": guild.name,
                "icon": str(guild.icon.url) if guild.icon else None,
                "member_count": guild.member_count,
            },
            "all_guilds": _list_visible_guilds(session, bot),
        },
    )
