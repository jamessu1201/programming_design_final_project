# -*- coding: utf-8 -*-
import discord
from discord.ext import commands


class CustomHelp(commands.HelpCommand):
    def __init__(self):
        super().__init__(
            command_attrs={
                "help": "顯示指令列表，或某個指令的詳細用法",
                "brief": "顯示指令說明",
            }
        )

    def _is_owner(self, ctx) -> bool:
        return ctx.author.id in (ctx.bot.owner_ids or set())

    def get_command_signature(self, command: commands.Command) -> str:
        prefix = self.context.clean_prefix
        parent = command.full_parent_name
        name = f"{parent} {command.name}".strip()
        sig = command.signature
        return f"{prefix}{name} {sig}".rstrip()

    @staticmethod
    def _short_doc(command: commands.Command) -> str:
        return command.short_doc or command.help or "—"

    async def send_bot_help(self, mapping):
        ctx = self.context
        is_owner = self._is_owner(ctx)

        embed = discord.Embed(
            title="📚 指令列表",
            description=(
                f"輸入 `{ctx.clean_prefix}help <指令>` 查看詳細用法\n"
                f"`<必填>` `[選填]`"
            ),
            color=discord.Color.blurple(),
        )

        ordered_cogs = sorted(
            (c for c in mapping if c is not None),
            key=lambda c: c.qualified_name.lower(),
        )

        for cog in ordered_cogs:
            visible = [c for c in mapping[cog] if not c.hidden]
            if not visible:
                continue
            lines = []
            for c in sorted(visible, key=lambda x: x.name):
                sig = self.get_command_signature(c)
                lines.append(f"`{sig}` — {self._short_doc(c)}")
            embed.add_field(
                name=cog.qualified_name,
                value="\n".join(lines),
                inline=False,
            )

        # Cogless commands
        none_cmds = [c for c in mapping.get(None, []) if not c.hidden]
        if none_cmds:
            lines = [
                f"`{self.get_command_signature(c)}` — {self._short_doc(c)}"
                for c in sorted(none_cmds, key=lambda x: x.name)
            ]
            embed.add_field(name="其他", value="\n".join(lines), inline=False)

        if is_owner:
            admin_lines = []
            for cog in ordered_cogs:
                hidden = [c for c in mapping[cog] if c.hidden]
                for c in sorted(hidden, key=lambda x: x.name):
                    sig = self.get_command_signature(c)
                    admin_lines.append(f"`{sig}` — {self._short_doc(c)}")
            for c in sorted(
                (x for x in mapping.get(None, []) if x.hidden),
                key=lambda x: x.name,
            ):
                sig = self.get_command_signature(c)
                admin_lines.append(f"`{sig}` — {self._short_doc(c)}")
            if admin_lines:
                embed.add_field(
                    name="🛠 Admin（僅 Owner）",
                    value="\n".join(admin_lines),
                    inline=False,
                )

        await self.get_destination().send(embed=embed)

    async def send_command_help(self, command: commands.Command):
        if command.hidden and not self._is_owner(self.context):
            return await self.send_error_message(self.command_not_found(command.name))

        embed = discord.Embed(
            title=f"指令: {command.qualified_name}",
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="用法",
            value=f"`{self.get_command_signature(command)}`",
            inline=False,
        )
        if command.help:
            embed.add_field(name="說明", value=command.help, inline=False)
        if command.aliases:
            embed.add_field(
                name="別名",
                value=", ".join(f"`{a}`" for a in command.aliases),
                inline=False,
            )
        if command.hidden:
            embed.set_footer(text="🛠 Admin / Owner-only")
        await self.get_destination().send(embed=embed)

    async def send_cog_help(self, cog: commands.Cog):
        await self.send_bot_help({cog: cog.get_commands()})

    async def send_group_help(self, group: commands.Group):
        await self.send_command_help(group)


class Help(commands.Cog):
    """指令說明。"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._original_help = bot.help_command
        bot.help_command = CustomHelp()
        bot.help_command.cog = self

    def cog_unload(self):
        self.bot.help_command = self._original_help


async def setup(bot: commands.Bot):
    await bot.add_cog(Help(bot))
