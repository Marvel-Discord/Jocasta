import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from config import homeserver

BIRTHDAY_ROLE_ID = 393425499474624512
BIRTHDAY_DURATION = 86400  # 24 hours in seconds


class BirthdayCog(commands.Cog, name="Birthday"):
    def __init__(self, bot):
        self.bot = bot
        self.bot.tasks["birthday"] = {}
        self.bot.loop.create_task(self.on_startup())

    async def on_startup(self):
        await self.bot.wait_until_ready()
        guild = self.bot.get_guild(homeserver)
        role = guild.get_role(BIRTHDAY_ROLE_ID)
        if role is None:
            return

        for member in role.members:
            if member.id not in self.bot.tasks["birthday"]:
                task = asyncio.create_task(self._remove_role_after_delay(member.id))
                self.bot.tasks["birthday"][member.id] = task

    async def _remove_role_after_delay(self, member_id: int, delay: float = BIRTHDAY_DURATION):
        await asyncio.sleep(delay)
        guild = self.bot.get_guild(homeserver)
        try:
            member = guild.get_member(member_id)
            if member:
                role = guild.get_role(BIRTHDAY_ROLE_ID)
                if role and role in member.roles:
                    await member.remove_roles(role, reason="Birthday role expired after 24 hours")
        except discord.HTTPException:
            pass
        finally:
            self.bot.tasks.get("birthday", {}).pop(member_id, None)

    @app_commands.command(name="birthday")
    @app_commands.describe(member="The member whose birthday it is")
    @app_commands.guilds(homeserver)
    @app_commands.checks.has_permissions(manage_roles=True)
    async def birthday(self, interaction: discord.Interaction, member: discord.Member):
        """Assigns the birthday role to a member for 24 hours, then removes it automatically."""
        role = interaction.guild.get_role(BIRTHDAY_ROLE_ID)
        if role is None:
            return await interaction.response.send_message(
                "Birthday role not found in this server.", ephemeral=True
            )

        existing = self.bot.tasks["birthday"].get(member.id)
        if existing and not existing.done():
            return await interaction.response.send_message(
                f"{member.mention} already has an active birthday timer running.", ephemeral=True
            )
        elif existing:
            self.bot.tasks["birthday"].pop(member.id, None)

        if role in member.roles:
            return await interaction.response.send_message(
                f"{member.mention} already has the birthday role.", ephemeral=True
            )

        await member.add_roles(role, reason=f"Birthday assigned by {interaction.user} ({interaction.user.id})")
        task = asyncio.create_task(self._remove_role_after_delay(member.id))
        self.bot.tasks["birthday"][member.id] = task

        await interaction.response.send_message(
            f"Happy birthday, {member.mention}! \N{BIRTHDAY CAKE} The birthday role will be removed automatically in 24 hours."
        )

    @birthday.error
    async def birthday_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            msg = "You don't have permission to use this command."
        else:
            msg = "Something went wrong."

        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

    async def cog_unload(self):
        for task in self.bot.tasks.get("birthday", {}).values():
            task.cancel()
        self.bot.tasks.pop("birthday", None)


async def setup(bot):
    await bot.add_cog(BirthdayCog(bot))
