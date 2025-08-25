
import nextcord
import nextcord as discord
from nextcord.ext import commands
from modules.economy import Economy
from modules.helpers import *


class GamblingHelpers(commands.Cog, name='General'):
    def __init__(self, client: commands.Bot) -> None:
        self.client = client
        from modules.economy import Economy
        from modules.helpers import DEFAULT_BET, B_MULT, B_COOLDOWN
        self.economy = Economy()
        self.default_bet = DEFAULT_BET
        self.bonus_multiplier = B_MULT
        self.bonus_cooldown = B_COOLDOWN

    @commands.command(hidden=True)
    @commands.is_owner()
    async def set(
        self,
        ctx: commands.Context,
        user_id: int=None,
        money: int=0,
        credits: int=0
    ):
        if money:
            self.economy.set_money(user_id, money)
        if credits:
            self.economy.set_credits(user_id, credits)

    @commands.command(
        brief="Gives you your bonus once every set cooldown hours.",
        usage="add"
    )
    @commands.cooldown(1, 1, type=commands.BucketType.user)  # Cooldown set dynamically
    async def add(self, ctx: commands.Context):
        amount = self.default_bet * self.bonus_multiplier
        self.economy.add_money(ctx.author.id, amount)
        await ctx.send(f"Added ${amount} come back in {self.bonus_cooldown}hrs")

    from modules.helpers import TEST_GUILD_ID
    @nextcord.slash_command(
        name="balance",
        description="Show your cash and slot credits. Optionally check another user's balance.",
        guild_ids=[TEST_GUILD_ID]
    )
    async def balance(self, interaction: nextcord.Interaction, user: nextcord.Member = None):
        from modules.helpers import CASINO_CHANNEL_ID
        if interaction.channel.id != CASINO_CHANNEL_ID:
            await interaction.response.send_message("This command can only be used in the designated casino channel.", ephemeral=True)
            return
        user = user or interaction.user
        profile = self.economy.get_entry(user.id)
        embed = make_embed(
            title=f"{user.display_name}'s Balance",
            description=(
                f'**${profile[1]:,}** cash' +
                f'\n**{profile[2]:,}** credits'
            )
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        await interaction.response.send_message(embed=embed, ephemeral=(user == interaction.user))

    @commands.command(
        brief="Shows the user with the most money",
        usage="leaderboard",
        aliases=["top"]
    )
    async def leaderboard(self, ctx):
        entries = self.economy.top_entries(5)
        embed = make_embed(title='Leaderboard:', color=discord.Color.gold())
        for i, entry in enumerate(entries):
            embed.add_field(
                name=f"{i+1}. {self.client.get_user(entry[0]).name}",
                value='${:,}'.format(entry[1]),
                inline=False
            )
        await ctx.send(embed=embed)

def setup(client: commands.Bot):
    client.add_cog(GamblingHelpers(client))