# -*- coding: utf-8 -*-
"""Session, CSRF, and access-control helpers for the dashboard."""
from __future__ import annotations

import json
import logging
import os
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import Depends, HTTPException, Path as FPath, Request
from itsdangerous import BadSignature, URLSafeTimedSerializer

logger = logging.getLogger(__name__)

SESSION_COOKIE = "dashboard_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 14  # 14 days
OAUTH_STATE_MAX_AGE = 60 * 5  # 5 minutes

OAUTH_CONFIG_PATH = Path("api_key/oauth.json")
SESSION_KEY_PATH = Path("api_key/session.key")


@dataclass
class Session:
    user_id: int
    username: str
    avatar: Optional[str]
    allowed_guilds: list[int] = field(default_factory=list)
    is_owner: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Session":
        return cls(
            user_id=int(data["user_id"]),
            username=str(data.get("username", "")),
            avatar=data.get("avatar"),
            allowed_guilds=[int(g) for g in data.get("allowed_guilds", [])],
            is_owner=bool(data.get("is_owner", False)),
        )


def load_oauth_config() -> dict:
    if not OAUTH_CONFIG_PATH.exists():
        raise FileNotFoundError(
            f"{OAUTH_CONFIG_PATH} not found. Copy oauth.json.example and fill it in."
        )
    with OAUTH_CONFIG_PATH.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    for key in ("client_id", "client_secret", "redirect_uri"):
        if not cfg.get(key):
            raise ValueError(f"oauth.json missing required field: {key}")
    cfg.setdefault("host", "127.0.0.1")
    cfg.setdefault("port", 8080)
    return cfg


def load_session_secret() -> bytes:
    SESSION_KEY_PATH.parent.mkdir(exist_ok=True)
    if SESSION_KEY_PATH.exists():
        return SESSION_KEY_PATH.read_bytes()
    secret = secrets.token_bytes(32)
    SESSION_KEY_PATH.write_bytes(secret)
    os.chmod(SESSION_KEY_PATH, 0o600)
    logger.info("Generated new dashboard session secret at %s", SESSION_KEY_PATH)
    return secret


def session_serializer(request: Request) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(request.app.state.session_secret, salt="session")


def state_serializer(request: Request) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(request.app.state.session_secret, salt="oauth-state")


def csrf_serializer(secret: bytes) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret, salt="csrf")


def encode_session(secret: bytes, session: Session) -> str:
    return URLSafeTimedSerializer(secret, salt="session").dumps(session.to_dict())


def decode_session(secret: bytes, raw: str) -> Optional[Session]:
    try:
        data = URLSafeTimedSerializer(secret, salt="session").loads(
            raw, max_age=SESSION_MAX_AGE
        )
        return Session.from_dict(data)
    except (BadSignature, ValueError, KeyError) as e:
        logger.debug("Session decode failed: %s", e)
        return None


def load_session(request: Request) -> Optional[Session]:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    return decode_session(request.app.state.session_secret, raw)


def require_session(request: Request) -> Session:
    s = load_session(request)
    if s is None:
        raise HTTPException(status_code=401, detail="login required")
    return s


def require_owner(request: Request) -> Session:
    s = require_session(request)
    if not s.is_owner:
        raise HTTPException(status_code=403, detail="owner only")
    return s


def require_guild_access(
    guild_id: int = FPath(..., description="Discord guild id"),
    request: Request = None,  # type: ignore
) -> Session:
    s = require_session(request)
    if s.is_owner:
        return s
    if guild_id not in s.allowed_guilds:
        raise HTTPException(status_code=403, detail="no access to this guild")
    return s


def generate_csrf(session: Session, secret: bytes) -> str:
    return csrf_serializer(secret).dumps(str(session.user_id))


def verify_csrf(session: Session, token: str, secret: bytes, max_age: int = SESSION_MAX_AGE) -> bool:
    try:
        uid = csrf_serializer(secret).loads(token, max_age=max_age)
        return uid == str(session.user_id)
    except (BadSignature, ValueError):
        return False


async def require_csrf(request: Request, session: Session = Depends(require_session)) -> Session:
    """Use as a dependency on POST routes to enforce CSRF check."""
    form = await request.form()
    token = form.get("_csrf", "")
    if not verify_csrf(session, token, request.app.state.session_secret):
        raise HTTPException(status_code=403, detail="bad csrf token")
    return session
