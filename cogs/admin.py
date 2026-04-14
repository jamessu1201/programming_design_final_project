# -*- coding: utf-8 -*-
import asyncio
import importlib
import json
import logging
import os
import subprocess
import sys
import yaml

import discord
from discord.ext import commands, tasks

logger = logging.getLogger(__name__)

EXTERNAL_MODULES = ["leetcode", "attend_playwright", "attend_program"]
AUTO_DEPLOY_INTERVAL = 30  # seconds
AUTO_DEPLOY_STATE = "json/autodeploy.json"


def _read_autodeploy_state():
    try:
        with open(AUTO_DEPLOY_STATE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_autodeploy_state(state):
    os.makedirs(os.path.dirname(AUTO_DEPLOY_STATE), exist_ok=True)
    with open(AUTO_DEPLOY_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f)


class Admin(commands.Cog):
    """Admin-only commands that make the bot dynamic."""

    def __init__(self, bot):
        self.bot = bot
        self._auto_deploy = False
        self._deploy_channel = None
        self._resume_task = bot.loop.create_task(self._maybe_resume_autodeploy())

    def cog_unload(self):
        if self.git_poll.is_running():
            self.git_poll.cancel()
        if self._resume_task and not self._resume_task.done():
            self._resume_task.cancel()

    async def _maybe_resume_autodeploy(self):
        """If autodeploy was on before a reload/restart, turn it back on."""
        await self.bot.wait_until_ready()
        state = _read_autodeploy_state()
        if not state.get("enabled"):
            return
        channel_id = state.get("channel_id")
        if not channel_id:
            return
        try:
            channel = await self.bot.fetch_channel(channel_id)
        except discord.HTTPException as e:
            logger.warning("Cannot resume autodeploy, channel fetch failed: %s", e)
            return
        self._deploy_channel = channel
        self._auto_deploy = True
        if not self.git_poll.is_running():
            self.git_poll.start()
        logger.info("Auto-deploy resumed on #%s", getattr(channel, "name", channel_id))

    # ── Helpers ──

    def _reload_external(self, names=None):
        """Reload project-root modules. If names is None, reload all known."""
        targets = names if names is not None else EXTERNAL_MODULES
        reloaded = []
        for name in targets:
            if name in sys.modules:
                try:
                    importlib.reload(sys.modules[name])
                    reloaded.append(name)
                except Exception as e:
                    logger.warning("Failed to reload %s: %s", name, e)
        return reloaded

    async def _run_git(self, *args):
        """Run a git command async and return stdout."""
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return stdout.decode().strip(), stderr.decode().strip(), proc.returncode

    async def _pull_and_reload(self):
        """Fetch, check diff, pull, reload changed files. Returns summary or None."""
        # fetch
        _, fetch_err, rc = await self._run_git("fetch")
        if rc != 0:
            logger.warning("git fetch failed (rc=%s): %s", rc, fetch_err)
            return None

        # only count commits that are on FETCH_HEAD but not on HEAD
        count_out, _, rc = await self._run_git(
            "rev-list", "--count", "HEAD..FETCH_HEAD"
        )
        if rc != 0 or not count_out or count_out == "0":
            return None

        # list files that changed in those upstream commits
        diff_out, _, _ = await self._run_git(
            "diff", "--name-only", "HEAD", "FETCH_HEAD"
        )
        if not diff_out:
            return None

        changed_files = diff_out.split("\n")
        logger.info("Git changes detected: %s", changed_files)

        # pull
        pull_out, pull_err, rc = await self._run_git("pull", "--ff-only")
        if rc != 0:
            logger.error("Git pull failed: %s", pull_err)
            return f"Git pull failed: {pull_err}"

        # figure out what to reload
        ext_to_reload = []
        cogs_to_reload = []
        config_changed = False

        for f in changed_files:
            f = f.strip()
            if f == "config.yaml":
                config_changed = True
            elif f.startswith("cogs/") and f.endswith(".py"):
                cog_name = f.replace("cogs/", "").replace(".py", "")
                cogs_to_reload.append(cog_name)
            elif f.endswith(".py") and "/" not in f:
                mod_name = f.replace(".py", "")
                if mod_name in EXTERNAL_MODULES:
                    ext_to_reload.append(mod_name)

        # reload config
        if config_changed:
            try:
                with open("config.yaml", "r", encoding="utf-8") as cf:
                    self.bot.config = yaml.safe_load(cf)
                logger.info("config.yaml reloaded")
            except Exception as e:
                logger.error("Failed to reload config.yaml: %s", e)

        # reload external modules
        reloaded_ext = self._reload_external(ext_to_reload) if ext_to_reload else []

        # reload cogs
        success = []
        failed = []
        for cog_name in cogs_to_reload:
            ext_key = f"cogs.{cog_name}"
            if ext_key in self.bot.extensions:
                try:
                    await self.bot.reload_extension(ext_key)
                    success.append(cog_name)
                except Exception as e:
                    failed.append(f"{cog_name}: {e}")
            else:
                try:
                    await self.bot.load_extension(ext_key)
                    success.append(f"{cog_name}(new)")
                except Exception as e:
                    failed.append(f"{cog_name}: {e}")

        # build summary
        parts = []
        parts.append(f"**Git pull**: {len(changed_files)} files changed")
        if config_changed:
            parts.append("config.yaml reloaded")
        if reloaded_ext:
            parts.append(f"External: {', '.join(reloaded_ext)}")
        if success:
            parts.append(f"Cogs reloaded: {', '.join(success)}")
        if failed:
            parts.append(f"Failed: {'; '.join(failed)}")
        return "\n".join(parts)

    # ── Auto deploy loop ──

    @tasks.loop(seconds=AUTO_DEPLOY_INTERVAL)
    async def git_poll(self):
        try:
            result = await self._pull_and_reload()
            if result and self._deploy_channel:
                await self._deploy_channel.send(f"🔄 Auto-deploy:\n{result}")
        except Exception as e:
            logger.error("Auto-deploy error: %s", e)

    @git_poll.before_loop
    async def before_git_poll(self):
        await self.bot.wait_until_ready()

    # ── Commands ──

    @commands.command(hidden=True)
    @commands.is_owner()
    async def load(self, ctx: commands.Context, module: str = None):
        """Loads a module."""
        if module is None:
            return await ctx.send("please enter a module.")
        try:
            await self.bot.load_extension(f"cogs.{module}")
        except Exception as e:
            await ctx.send(f"\N{PISTOL} {type(e).__name__}: {e}")
        else:
            await ctx.send("\N{OK HAND SIGN}")

    @commands.command(hidden=True)
    @commands.is_owner()
    async def unload(self, ctx: commands.Context, module: str = None):
        """Unloads a module."""
        if module is None:
            return await ctx.send("please enter a module.")
        try:
            await self.bot.unload_extension(f"cogs.{module}")
        except Exception as e:
            await ctx.send(f"\N{PISTOL} {type(e).__name__}: {e}")
        else:
            await ctx.send("\N{OK HAND SIGN}")

    @commands.command(name="reload", hidden=True)
    @commands.is_owner()
    async def _reload(self, ctx: commands.Context, module: str = None):
        """Reloads a module (also reloads external deps)."""
        if module is None:
            return await ctx.send("please enter a module.")
        try:
            reloaded = self._reload_external()
            await self.bot.reload_extension(f"cogs.{module}")
        except Exception as e:
            await ctx.send(f"\N{PISTOL} {type(e).__name__}: {e}")
        else:
            msg = "\N{OK HAND SIGN}"
            if reloaded:
                msg += f" (also reloaded: {', '.join(reloaded)})"
            await ctx.send(msg)

    @commands.command(name="reload_all", aliases=["ra"], hidden=True)
    @commands.is_owner()
    async def _reload_all(self, ctx: commands.Context):
        """Reload all external modules + all cogs at once."""
        reloaded_ext = self._reload_external()
        success, failed = [], []
        for ext_name in list(self.bot.extensions):
            if ext_name == "cogs.admin":
                continue
            try:
                await self.bot.reload_extension(ext_name)
                success.append(ext_name.replace("cogs.", ""))
            except Exception as e:
                failed.append(f"{ext_name.replace('cogs.', '')}: {e}")
        try:
            await self.bot.reload_extension("cogs.admin")
            success.append("admin")
        except Exception as e:
            failed.append(f"admin: {e}")

        msg = f"Reloaded {len(success)} cogs: {', '.join(success)}"
        if reloaded_ext:
            msg += f"\nExternal: {', '.join(reloaded_ext)}"
        if failed:
            msg += f"\nFailed: {'; '.join(failed)}"
        await ctx.send(msg)

    @commands.command(name="deploy", hidden=True)
    @commands.is_owner()
    async def _deploy(self, ctx: commands.Context):
        """Manual git pull + reload changed files."""
        await ctx.send("Pulling from git...")
        result = await self._pull_and_reload()
        if result:
            await ctx.send(result)
        else:
            await ctx.send("Already up to date.")

    @commands.command(name="autodeploy", aliases=["ad"], hidden=True)
    @commands.is_owner()
    async def _autodeploy(self, ctx: commands.Context):
        """Toggle auto-deploy: polls git every 30s, auto pulls & reloads."""
        if self.git_poll.is_running():
            self.git_poll.cancel()
            self._auto_deploy = False
            _write_autodeploy_state({"enabled": False})
            await ctx.send("Auto-deploy **OFF**")
        else:
            self._deploy_channel = ctx.channel
            self.git_poll.start()
            self._auto_deploy = True
            _write_autodeploy_state({
                "enabled": True,
                "channel_id": ctx.channel.id,
            })
            await ctx.send(
                f"Auto-deploy **ON** (polling every {AUTO_DEPLOY_INTERVAL}s, reporting here)"
            )

    @commands.command(name="botstop", aliases=["bstop", "shutdown", "bye"], hidden=True)
    @commands.is_owner()
    async def botstop(self, ctx):
        """關閉機器人"""
        logger.info("Goodbye")
        await ctx.send("Goodbye")
        await self.bot.close()

    @commands.command(name="sync", hidden=True)
    @commands.is_owner()
    async def _sync(self, ctx: commands.Context, scope: str = "guild"):
        """同步 slash commands。scope=guild(當前伺服器，立即生效) / global(全域，最多 1 小時)"""
        try:
            if scope == "global":
                synced = await self.bot.tree.sync()
                await ctx.send(f"已全域同步 {len(synced)} 個 slash commands（最多 1 小時生效）")
            else:
                self.bot.tree.copy_global_to(guild=ctx.guild)
                synced = await self.bot.tree.sync(guild=ctx.guild)
                await ctx.send(f"已在本伺服器同步 {len(synced)} 個 slash commands")
        except discord.DiscordServerError as e:
            logger.warning("Discord API unavailable during sync: %s", e)
            await ctx.send(f"⚠️ Discord API 暫時不穩（{e.status}），等幾分鐘再試一次")
        except discord.HTTPException as e:
            logger.error("Sync failed: %s", e)
            await ctx.send(f"❌ 同步失敗：{e}")


async def setup(bot):
    await bot.add_cog(Admin(bot))
