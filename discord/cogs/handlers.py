import logging

import nextcord as discord
from nextcord.ext import commands
from nextcord.ext.commands.errors import *
from modules.helpers import PREFIX, InsufficientFundsException

log = logging.getLogger(__name__)


def cooldown_text(seconds: float) -> str:
    h, rest = divmod(int(seconds) % (24 * 3600), 3600)
    m, s = divmod(rest, 60)
    return f"{h}hrs {m}min {s}sec remaining."


class Handlers(commands.Cog, name='handlers'):
    def __init__(self, client: commands.Bot):
        self.client = client

    @commands.Cog.listener()
    async def on_ready(self):
        log.info("%s is ready", self.client.user.name)
        try:
            await self.client.change_presence(activity=discord.Game("blackjack | /help"))
        except discord.HTTPException as e:
            log.warning("Could not set presence: %s", e)

    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error):
        if hasattr(ctx.command, 'on_error'):
            return
        if isinstance(error, CommandInvokeError):  # the real error is inside
            error = error.original

        if isinstance(error, CommandNotFound):
            # No help command is registered (help_command=None), so just point to slash commands.
            if ctx.message.content.startswith(PREFIX) and len(ctx.message.content) > len(PREFIX):
                await ctx.send("Unknown command. Use the slash commands, try `/help`.")
        elif isinstance(error, (MissingRequiredArgument, TooManyArguments, BadArgument)):
            usage = f"{PREFIX}{ctx.command.name} {ctx.command.usage or ctx.command.signature}".strip()
            await ctx.send(f"Usage: `{usage}`")
        elif isinstance(error, (UserNotFound, MemberNotFound)):
            await ctx.send(f"Member, `{error.argument}`, was not found.")
        elif isinstance(error, MissingPermissions):
            await ctx.send("Must have following permission(s): " +
                           ", ".join(f'`{perm}`' for perm in error.missing_permissions))
        elif isinstance(error, BotMissingPermissions):
            await ctx.send("I must have following permission(s): " +
                           ", ".join(f'`{perm}`' for perm in error.missing_permissions))
        elif isinstance(error, InsufficientFundsException):
            await ctx.send("You don't have enough chips. Use /cashier or /buy to get more.")
        elif isinstance(error, CommandOnCooldown):
            await ctx.send(cooldown_text(error.retry_after))
        elif not isinstance(error, (CheckFailure, NotOwner)):  # a failed permission check is not a bug
            log.error("Unhandled error in command %s", ctx.command, exc_info=error)


def setup(client: commands.Bot):
    client.add_cog(Handlers(client))
