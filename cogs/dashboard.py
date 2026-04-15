# -*- coding: utf-8 -*-
"""Boot the FastAPI dashboard inside the bot's event loop."""
from __future__ import annotations

import asyncio
import logging
import sys

import uvicorn
from discord.ext import commands

logger = logging.getLogger(__name__)


class Dashboard(commands.Cog):
    """Serves the management web dashboard alongside the bot."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._server: uvicorn.Server | None = None
        self._task: asyncio.Task | None = None

    async def cog_load(self):
        # Force re-import of dashboard.* so reloads pick up new routes /
        # templates without needing a full bot restart.
        for name in list(sys.modules):
            if name == "dashboard" or name.startswith("dashboard."):
                del sys.modules[name]

        try:
            from dashboard.app import create_app
            app = create_app(self.bot)
        except FileNotFoundError as e:
            logger.warning("Dashboard not started: %s", e)
            return
        except ValueError as e:
            logger.error("Dashboard config invalid: %s", e)
            return
        except Exception as e:
            logger.exception("Dashboard create_app failed: %s", e)
            return

        cfg = app.state.oauth_config
        config = uvicorn.Config(
            app,
            host=cfg.get("host", "127.0.0.1"),
            port=int(cfg.get("port", 8080)),
            log_level="info",
            access_log=False,
            loop="asyncio",
            lifespan="off",
        )
        self._server = uvicorn.Server(config)
        # uvicorn.Server.serve() returns when the server stops
        self._task = asyncio.create_task(self._server.serve())
        logger.info(
            "Dashboard listening on http://%s:%s",
            cfg.get("host", "127.0.0.1"),
            cfg.get("port", 8080),
        )

    async def cog_unload(self):
        if self._server is not None:
            self._server.should_exit = True
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except asyncio.TimeoutError:
                logger.warning("Dashboard server did not stop in time, cancelling")
                self._task.cancel()


async def setup(bot: commands.Bot):
    await bot.add_cog(Dashboard(bot))
