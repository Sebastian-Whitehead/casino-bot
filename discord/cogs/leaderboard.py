import nextcord as discord
from nextcord.ext import commands
from modules.game_ui import ensure_casino_channel, format_chips
from modules.helpers import TEST_GUILD_ID

class Leaderboard(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @discord.slash_command(
        description="Show the top 10 players by chips.",
        **({"guild_ids": [TEST_GUILD_ID]})
    )
    async def casino_leaderboard(self, interaction: discord.Interaction) -> None:
        if not await ensure_casino_channel(interaction):
            return
        from modules.economy import Economy
        econ = Economy()
        # entries are (user_id, money, chips); the casino account is excluded
        filtered = [e for e in econ.get_all_entries() if e[0] != econ.casino_user_id]
        top = sorted(filtered, key=lambda x: x[2], reverse=True)[:10]
        if not top:
            await interaction.response.send_message("No users found in the casino database.", ephemeral=True)
            return
        lines = []
        for i, (user_id, money, chips) in enumerate(top, 1):
            try:
                user = await self.client.fetch_user(user_id)
                name = user.display_name if user else str(user_id)
            except Exception:
                name = str(user_id)
            lines.append(f"{i}. {name}: {format_chips(chips)}")
        await interaction.response.send_message("**Casino Leaderboard (chips)**\n" + "\n".join(lines), ephemeral=True)

def setup(client):
    client.add_cog(Leaderboard(client))
