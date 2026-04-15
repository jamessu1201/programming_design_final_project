# -*- coding: utf-8 -*-
"""Discord OAuth2 login flow."""
from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from itsdangerous import BadSignature, URLSafeTimedSerializer

from .. import security
from ..limits import limiter

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

OAUTH_AUTHORIZE = "https://discord.com/api/oauth2/authorize"
OAUTH_TOKEN = "https://discord.com/api/oauth2/token"
OAUTH_USER_ME = "https://discord.com/api/users/@me"
OAUTH_USER_GUILDS = "https://discord.com/api/users/@me/guilds"
OAUTH_SCOPE = "identify guilds"

PERM_MANAGE_GUILD = 1 << 5  # 0x20


def _serializer(request: Request, salt: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(request.app.state.session_secret, salt=salt)


@router.get("/login")
@limiter.limit("20/minute")
async def login(request: Request):
    cfg = request.app.state.oauth_config
    nonce = secrets.token_urlsafe(16)
    state = _serializer(request, "oauth-state").dumps(nonce)
    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "response_type": "code",
        "scope": OAUTH_SCOPE,
        "state": state,
        "prompt": "none",
    }
    url = f"{OAUTH_AUTHORIZE}?{urlencode(params)}"
    return RedirectResponse(url=url, status_code=302)


@router.get("/logout")
async def logout(request: Request):
    resp = RedirectResponse(url="/", status_code=302)
    resp.delete_cookie(security.SESSION_COOKIE)
    return resp


@router.get("/callback")
@limiter.limit("10/minute")
async def callback(request: Request, code: str = "", state: str = ""):
    cfg = request.app.state.oauth_config
    if not code or not state:
        raise HTTPException(400, "missing code or state")
    try:
        _serializer(request, "oauth-state").loads(state, max_age=security.OAUTH_STATE_MAX_AGE)
    except (BadSignature, ValueError) as e:
        logger.warning("OAuth state validation failed: %s", e)
        raise HTTPException(400, "invalid state")

    async with httpx.AsyncClient(timeout=15) as client:
        token_resp = await client.post(
            OAUTH_TOKEN,
            data={
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": cfg["redirect_uri"],
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_resp.status_code != 200:
            logger.error("OAuth token exchange failed: %s %s", token_resp.status_code, token_resp.text)
            raise HTTPException(502, "token exchange failed")
        access_token = token_resp.json()["access_token"]

        headers = {"Authorization": f"Bearer {access_token}"}
        me_resp = await client.get(OAUTH_USER_ME, headers=headers)
        guilds_resp = await client.get(OAUTH_USER_GUILDS, headers=headers)

    if me_resp.status_code != 200 or guilds_resp.status_code != 200:
        raise HTTPException(502, "discord api error")

    me = me_resp.json()
    user_id = int(me["id"])
    username = me.get("global_name") or me.get("username") or "?"
    avatar_hash = me.get("avatar")
    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{user_id}/{avatar_hash}.png"
        if avatar_hash else None
    )

    bot = request.app.state.bot
    is_owner = user_id in (bot.owner_ids or set())

    allowed_guilds: list[int] = []
    user_guild_ids = {int(g["id"]) for g in guilds_resp.json()}
    for guild in bot.guilds:
        if guild.id not in user_guild_ids:
            continue
        if is_owner:
            allowed_guilds.append(guild.id)
            continue
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except Exception:
                member = None
        if member and member.guild_permissions.manage_guild:
            allowed_guilds.append(guild.id)

    if not is_owner and not allowed_guilds:
        raise HTTPException(403, "你沒有任何可管理的伺服器")

    session = security.Session(
        user_id=user_id,
        username=username,
        avatar=avatar_url,
        allowed_guilds=allowed_guilds,
        is_owner=is_owner,
    )
    cookie_value = security.encode_session(request.app.state.session_secret, session)

    resp = RedirectResponse(url="/", status_code=302)
    resp.set_cookie(
        security.SESSION_COOKIE,
        cookie_value,
        max_age=security.SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
    )
    logger.info(
        "Login: %s (%s) is_owner=%s guilds=%s",
        username, user_id, is_owner, len(allowed_guilds),
    )
    return resp
