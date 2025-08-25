import nextcord as discord
from nextcord.ext import commands
from modules.helpers import TEST_GUILD_ID

class Leaderboard(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client

    @discord.slash_command(
        description="Show the top 10 users by casino balance.",
        **({"guild_ids": [TEST_GUILD_ID]})
    )
    async def casino_leaderboard(self, interaction: discord.Interaction) -> None:
        """Slash command to show the top 10 users by casino balance."""
        from modules.economy import Economy, CASINO_USER_ID
        econ = Economy()
        all_entries = econ.get_all_entries()  # Should return list of (user_id, money, credits)
        # Exclude the bot's own entry (CASINO_USER_ID)
        filtered = [entry for entry in all_entries if entry[0] != CASINO_USER_ID]
        top = sorted(filtered, key=lambda x: x[1], reverse=True)[:10]
        if not top:
            await interaction.response.send_message("No users found in the casino database.", ephemeral=True)
            return
        lines = []
        for i, (user_id, money, credits) in enumerate(top, 1):
            try:
                user = await self.client.fetch_user(user_id)
                name = user.display_name if user else str(user_id)
            except Exception:
                name = str(user_id)
            lines.append(f"{i}. {name}: ${money}")
        leaderboard = "\n".join(lines)
        await interaction.response.send_message(f"**Casino Leaderboard**\n{leaderboard}", ephemeral=True)

def setup(client):
    client.add_cog(Leaderboard(client))
