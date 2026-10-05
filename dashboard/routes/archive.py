# -*- coding: utf-8 -*-
"""訊息統計（唯讀）：選人、選日期範圍，看講了幾句、在哪、幾點。資料來自 cogs/archive.py 的 SQLite。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request

from .. import security
from cogs import archive as archive_cog

router = APIRouter(prefix="/guilds/{guild_id}/archive", tags=["archive"])


def _bars(values: list[int]) -> list[dict]:
    peak = max(values) if values else 0
    return [{"n": n, "pct": round(n / peak * 100) if peak else 0} for n in values]


@router.get("")
async def stats_page(
    request: Request,
    guild_id: int,
    user_id: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    session: security.Session = Depends(security.require_guild_access),
):
    bot = request.app.state.bot
    guild = bot.get_guild(guild_id)
    enabled = archive_cog.archive_enabled(bot, guild_id)
    ctx = {
        "session": session,
        "guild": {
            "id": guild_id,
            "name": guild.name if guild else "(unknown)",
            "icon": str(guild.icon.url) if guild and guild.icon else None,
        },
        "enabled": enabled,
        "error": None,
        "users": [],
        "selected_user": user_id or "",
        "from_date": from_date or "",
        "to_date": to_date or "",
        "label": "",
        "stats": None,
        "top": [],
        "overview": None,
        "hour_bars": [],
        "weekday_bars": [],
        "weekday_names": archive_cog.WEEKDAY_NAMES,
    }
    if enabled:
        cog = bot.get_cog("Archive")
        if cog is not None:
            cog._flush_now()
        db = cog.db() if cog is not None else archive_cog.ArchiveDB()
        ctx["users"] = db.known_users(guild_id)
        ctx["overview"] = db.overview(guild_id)
        try:
            start, end, label = archive_cog.parse_range(from_date or None, to_date or None)
            ctx["label"] = label
        except ValueError as e:
            ctx["error"] = f"日期格式請用 YYYY-MM-DD（{e}）"
        else:
            if user_id:
                try:
                    uid = int(user_id)
                except ValueError:
                    ctx["error"] = "user_id 不是數字"
                else:
                    s = db.user_stats(guild_id, uid, start, end)
                    ctx["stats"] = s
                    ctx["hour_bars"] = _bars(s["hours"])
                    ctx["weekday_bars"] = _bars(s["weekdays"])
                    ctx["selected_name"] = next(
                        (u["name"] for u in ctx["users"] if u["user_id"] == uid), str(uid))
            else:
                ctx["top"] = db.top_users(guild_id, start, end, limit=30)
    return request.app.state.templates.TemplateResponse(request, "archive.html", ctx)
