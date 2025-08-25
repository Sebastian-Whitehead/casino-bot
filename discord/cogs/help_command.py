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
            value="Play the slot machine. Set your bet in credits, then spin for a chance at big multipliers!",
            inline=False
        )
        embed.add_field(
            name="/coinflip",
            value="Flip a coin and bet on heads or tails. Set your bet, then choose your side.",
            inline=False
        )
        embed.add_field(
            name="/diceroll",
            value="Roll a die and bet on the outcome (1-6). Set your bet, then guess the result.",
            inline=False
        )
        embed.add_field(
            name="/balance [user]",
            value="Show your cash and slot credits. Optionally check another user's balance.",
            inline=False
        )
        embed.add_field(
            name="/buyc amount_to_buy",
            value="Buy slot credits with your cash balance.",
            inline=False
        )
        embed.add_field(
            name="/sellc amount_to_sell",
            value="Sell slot credits for cash.",
            inline=False
        )
        embed.set_footer(text="All games use slash commands. Use the betting window to set your wager before starting each game.")
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
