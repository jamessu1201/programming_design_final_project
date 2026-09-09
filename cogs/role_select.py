# -*- coding: utf-8 -*-
import logging
import discord
from discord.ext import commands
from discord.ui import View, Button

logger = logging.getLogger(__name__)


class RoleButton(Button):
    def __init__(self, role_id: int, label: str, emoji: str = None):
        super().__init__(
            style=discord.ButtonStyle.primary,
            label=label,
            emoji=emoji,
            custom_id=f"role_select:{role_id}",
        )
        self.role_id = role_id

    async def callback(self, interaction: discord.Interaction):
        role = interaction.guild.get_role(self.role_id)
        if role is None:
            return await interaction.response.send_message(
                "找不到這個身分組", ephemeral=True
            )

        if role in interaction.user.roles:
            await interaction.user.remove_roles(role)
            await interaction.response.send_message(
                f"已移除 **{role.name}**", ephemeral=True
            )
        else:
            await interaction.user.add_roles(role)
            await interaction.response.send_message(
                f"已領取 **{role.name}**", ephemeral=True
            )


class PersistentRoleView(View):
    def __init__(self, roles_config: list):
        super().__init__(timeout=None)
        for r in roles_config:
            self.add_item(RoleButton(
                role_id=r["id"],
                label=r["label"],
                emoji=r.get("emoji"),
            ))


class RoleSelect(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cfg = bot.config
        roles_config = self.cfg.get("role_select", [])
        self.view = PersistentRoleView(roles_config)
        bot.add_view(self.view)

    @commands.command(name="setup_roles", hidden=True)
    @commands.is_owner()
    async def setup_roles(self, ctx: commands.Context):
        """發送身分組領取訊息到指定頻道"""
        channel_id = self.cfg.get("channels_extra", {}).get("role_select")
        if channel_id:
            channel = await self.bot.fetch_channel(channel_id)
        else:
            channel = ctx.channel

        roles_config = self.cfg.get("role_select", [])
        if not roles_config:
            return await ctx.send("config.yaml 裡沒有設定 role_select")

        embed = discord.Embed(
            title="身分組領取",
            description="點擊按鈕領取或移除身分組：\n\n"
            + "\n".join(
                f"{r.get('emoji', '•')} **{r['label']}**"
                for r in roles_config
            ),
            color=discord.Color.blue(),
        )

        view = PersistentRoleView(roles_config)
        await channel.send(embed=embed, view=view)
        if channel != ctx.channel:
            await ctx.send(f"已發送到 <#{channel_id}>")

    @commands.command(name="add_role_option", hidden=True)
    @commands.is_owner()
    async def add_role_option(self, ctx: commands.Context, role: discord.Role, *, label: str = None):
        """快速新增一個身分組選項到 config（需要重新 !setup_roles）"""
        roles_config = self.cfg.setdefault("role_select", [])
        for r in roles_config:
            if r["id"] == role.id:
                return await ctx.send(f"**{role.name}** 已經在列表中")

        roles_config.append({
            "id": role.id,
            "label": label or role.name,
            "emoji": "📌",
        })

        import yaml
        with open("config.yaml", "w", encoding="utf-8") as f:
            yaml.dump(self.cfg, f, allow_unicode=True, default_flow_style=False)

        await ctx.send(f"已新增 **{role.name}**，請執行 `!setup_roles` 重新發送訊息")


async def setup(bot):
    await bot.add_cog(RoleSelect(bot))
