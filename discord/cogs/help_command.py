import os

import nextcord
import nextcord as discord
from modules.helpers import ABS_PATH, make_embed
from nextcord.ext import commands
import os


class Help(commands.Cog, name='help'):
    def __init__(self, client: commands.Bot):
        self.client = client


    from modules.helpers import TEST_GUILD_ID
    @nextcord.slash_command(
        description="Show all casino bot slash commands and info.",
        guild_ids=[TEST_GUILD_ID]
    )
    async def help(self, interaction: nextcord.Interaction):
        embed = make_embed(title="Casino Bot Slash Commands")
        embed.add_field(
            name="/blackjack",
            value="Play a game of blackjack. Use the betting window to set your bet, then play against the dealer.",
            inline=False
        )
        embed.add_field(
            name="/slots",
            value="Play the slot machine. Set your bet in chips, then spin for a chance at big multipliers!",
            inline=False
        )
        embed.add_field(
            name="/coinflip",
            value="Flip a coin and bet on heads or tails, or challenge another user with /coinflip @user bet.",
            inline=False
        )
        embed.add_field(
            name="/diceroll",
            value="Roll a die and bet on the outcome (1-6), or challenge another user with /diceroll @user bet.",
            inline=False
        )
        embed.add_field(
            name="/balance [user]",
            value="Show your bank money and chips. Optionally check another user's balance.",
            inline=False
        )
        embed.add_field(
            name="/cashier",
            value="Open the chip cashier to buy chips with bank money or cash chips back out.",
            inline=False
        )
        embed.add_field(
            name="/buy amount",
            value="Buy that many chips with your bank money.",
            inline=False
        )
        embed.add_field(
            name="/cashout amount",
            value="Cash chips out to bank money. Use a number or `all`.",
            inline=False
        )
        embed.set_footer(text="All games are played with chips. Use the betting window to set your wager before starting each game.")
        fp = os.path.join(ABS_PATH, 'modules/cards/aces.png')
        file = discord.File(fp, filename='aces.png')
        embed.set_thumbnail(url=f"attachment://aces.png")
        await interaction.response.send_message(file=file, embed=embed, ephemeral=True)


    @commands.command(hidden=True)
    @commands.is_owner()
    async def kill(self, ctx: commands.Context):
        self.client.remove_cog('handlers')
        await self.client.logout()


def setup(client):
    client.add_cog(Help(client))
