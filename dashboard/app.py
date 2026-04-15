# -*- coding: utf-8 -*-
"""FastAPI factory for the bot dashboard."""
from __future__ import annotations

import datetime
import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from . import security
from .limits import limiter
from .routes import auth, autodeploy, autoreplies, banwords, guilds, maintenance, prefix

logger = logging.getLogger(__name__)

TEMPLATE_DIR = Path("dashboard/templates")
STATIC_DIR = Path("dashboard/static")


def create_app(bot) -> FastAPI:
    config = security.load_oauth_config()
    secret = security.load_session_secret()

    app = FastAPI(title="Bot Dashboard", docs_url=None, redoc_url=None)
    app.state.bot = bot
    app.state.oauth_config = config
    app.state.session_secret = secret
    app.state.start_time = datetime.datetime.now(datetime.timezone.utc)

    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)

    templates = Jinja2Templates(directory=str(TEMPLATE_DIR))
    templates.env.globals["csrf_for"] = lambda session: security.generate_csrf(
        session, secret
    )
    app.state.templates = templates

    STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    app.include_router(auth.router)
    app.include_router(guilds.router)
    app.include_router(banwords.router)
    app.include_router(autoreplies.router)
    app.include_router(prefix.router)
    app.include_router(autodeploy.router)
    app.include_router(maintenance.router)

    @app.exception_handler(401)
    async def _unauth(request: Request, _exc):
        return RedirectResponse(url="/auth/login", status_code=302)

    @app.exception_handler(403)
    async def _forbidden(request: Request, exc):
        return HTMLResponse(
            f"<h1>403 Forbidden</h1><p>{exc.detail}</p>"
            '<p><a href="/">回到首頁</a></p>',
            status_code=403,
        )

    return app
