import nextcord as discord
from nextcord.ext import commands
from modules.economy import Economy
from modules.game_ui import ensure_casino_channel, format_chips
from modules.helpers import GUILD_KW

GAMES = ["Blackjack", "Slots", "Coin Flip", "Dice Roll"]  # the game_name logged in game_log


class Leaderboard(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    async def _show(self, interaction, title, rows):
        if not rows:
            await interaction.response.send_message("No games have been played yet.", ephemeral=True)
            return
        lines = []
        for rank, user_id, won, lost, net in rows:
            try:
                user = await self.client.fetch_user(user_id)
                name = user.display_name if user else str(user_id)
            except Exception:
                name = str(user_id)
            lines.append(f"{rank}. {name}: {net:+,} net ({format_chips(won)} won, {format_chips(lost)} lost)")
        await interaction.response.send_message(f"**{title}**\n" + "\n".join(lines), ephemeral=True)

    @discord.slash_command(
        description="Show the top 10 players by net winnings.",
        **GUILD_KW
    )
    async def casino_leaderboard(self, interaction: discord.Interaction) -> None:
        if not await ensure_casino_channel(interaction):
            return
        await self._show(interaction, "Casino Leaderboard (net winnings)", Economy().leaderboard(10))

    @discord.slash_command(
        description="Show the top 10 players by net winnings in one game.",
        **GUILD_KW
    )
    async def game_leaderboard(
        self,
        interaction: discord.Interaction,
        game: str = discord.SlashOption(description="Which game", choices=GAMES),
    ) -> None:
        if not await ensure_casino_channel(interaction):
            return
        await self._show(interaction, f"{game} Leaderboard (net winnings)", Economy().leaderboard(10, game))

def setup(client):
    client.add_cog(Leaderboard(client))
