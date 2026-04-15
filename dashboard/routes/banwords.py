# -*- coding: utf-8 -*-
"""Per-guild banword CRUD."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from .. import audit, security

router = APIRouter(prefix="/guilds/{guild_id}/banwords", tags=["banwords"])

BADWORD_PATH = Path("json/badword.json")


def _load() -> dict:
    if not BADWORD_PATH.exists():
        return {}
    try:
        with BADWORD_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict) -> None:
    BADWORD_PATH.parent.mkdir(exist_ok=True)
    with BADWORD_PATH.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


@router.get("")
async def list_words(
    request: Request,
    guild_id: int,
    session: security.Session = Depends(security.require_guild_access),
):
    bot = request.app.state.bot
    guild = bot.get_guild(guild_id)
    words = _load().get(str(guild_id), [])
    return request.app.state.templates.TemplateResponse(
        request,
        "banwords.html",
        {
            "session": session,
            "guild": {
                "id": guild_id,
                "name": guild.name if guild else "(unknown)",
                "icon": str(guild.icon.url) if guild and guild.icon else None,
            },
            "words": words,
        },
    )


@router.post("/add")
async def add_word(
    request: Request,
    guild_id: int,
    word: str = Form(...),
    session: security.Session = Depends(security.require_csrf),
):
    # require_csrf only checks token; also enforce guild access
    if not session.is_owner and guild_id not in session.allowed_guilds:
        return RedirectResponse(url="/", status_code=302)

    word = word.strip()
    if not word or len(word) > 100:
        return RedirectResponse(
            url=f"/guilds/{guild_id}/banwords?error=invalid",
            status_code=303,
        )

    data = _load()
    bucket = data.setdefault(str(guild_id), [])
    if word in bucket:
        return RedirectResponse(
            url=f"/guilds/{guild_id}/banwords?error=duplicate",
            status_code=303,
        )
    before = list(bucket)
    bucket.append(word)
    _save(data)
    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=guild_id,
        route="banwords.add",
        action="add",
        before=before,
        after=list(bucket),
    )
    return RedirectResponse(url=f"/guilds/{guild_id}/banwords", status_code=303)


@router.post("/delete")
async def delete_word(
    request: Request,
    guild_id: int,
    word: str = Form(...),
    session: security.Session = Depends(security.require_csrf),
):
    if not session.is_owner and guild_id not in session.allowed_guilds:
        return RedirectResponse(url="/", status_code=302)

    data = _load()
    bucket = data.get(str(guild_id), [])
    if word not in bucket:
        return RedirectResponse(url=f"/guilds/{guild_id}/banwords", status_code=303)
    before = list(bucket)
    bucket.remove(word)
    if not bucket:
        data.pop(str(guild_id), None)
    _save(data)
    audit.write_audit(
        user_id=session.user_id,
        username=session.username,
        guild_id=guild_id,
        route="banwords.delete",
        action="delete",
        before=before,
        after=data.get(str(guild_id), []),
    )
    return RedirectResponse(url=f"/guilds/{guild_id}/banwords", status_code=303)
