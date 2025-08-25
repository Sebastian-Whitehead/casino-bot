"""
Main bot entrypoint for the casino bot.
Handles thread cleanup, owner commands, and casino stats.
"""

import logging
# --- Auto-delete dormant threads in a specific channel ---
ENABLE_AUTO_THREAD_CLEANUP = True  # Toggle this to enable/disable auto thread cleanup
from modules.auto_thread_cleanup import setup_auto_thread_cleanup, run_thread_cleanup

# Configure logging
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)
# Suppress nextcord and discord info/debug logs
logging.getLogger('nextcord').setLevel(logging.WARNING)
logging.getLogger('discord').setLevel(logging.WARNING)
# Suppress nextcord.ConnectionState logger entirely
logging.getLogger('nextcord.ConnectionState').setLevel(logging.CRITICAL)

# Use nextcord instead of discord.py for compatibility with your error
import nextcord as discord
from nextcord.ext import commands
from modules.helpers import *



# Explicitly set only the privileged intents you need
intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # Enable if your bot needs to read message content

client: commands.Bot = commands.Bot(
    command_prefix=PREFIX,
    owner_ids=OWNER_IDS,
    intents=intents,
    help_command=None
)

# Global event handler for thread deletions
@client.event
async def on_thread_delete(thread: discord.Thread):
    """Log when a thread is deleted."""
    parent = getattr(thread, 'parent', None)
    parent_name = getattr(parent, 'name', None) if parent else None
    logger.info(f"Thread '{thread.name}' (ID: {thread.id}) deleted in channel: {parent_name}")

from modules.helpers import TEST_GUILD_ID
USE_TEST_GUILD = True  # Set to True for fast test registration

@client.event
async def on_ready() -> None:
    """Bot startup event."""
    logger.info(f'Logged in as {client.user}')
    # Start background task for auto-deleting dormant threads
    if ENABLE_AUTO_THREAD_CLEANUP:
        setup_auto_thread_cleanup(client)

def _is_owner(interaction: discord.Interaction) -> bool:
    """Check if the user is a bot owner."""
    return interaction.user.id in OWNER_IDS

async def handle_cleanup_command(interaction: discord.Interaction) -> None:
    """Handle the /cleanup_threads command."""
    if not _is_owner(interaction):
        await interaction.response.send_message(
            "❌ You do not have permission to use this command.", ephemeral=True)
        return
    try:
        await interaction.response.defer(ephemeral=True)
        await run_thread_cleanup(client)
        await interaction.followup.send("Thread cleanup triggered.", ephemeral=True)
    except Exception as e:
        logger.error(f"[Cleanup Command] Error: {e}")

@client.slash_command(
    description="Manually trigger thread cleanup (owner only)",
    **({"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {})
)
async def cleanup_threads(interaction: discord.Interaction) -> None:
    """Slash command to manually trigger thread cleanup (owner only)."""
    await handle_cleanup_command(interaction)


# --- Simple in-memory casino balance variable ---
CASINO_BALANCE = 100000

@client.slash_command(
    description="Show the casino's current balance (owner only)",
    **({"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {})
)
async def casino_balance(interaction: discord.Interaction) -> None:
    """Slash command to show the casino's current balance (owner only)."""
    if not _is_owner(interaction):
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return
    global CASINO_BALANCE
    await interaction.response.send_message(f"Casino balance: ${CASINO_BALANCE}", ephemeral=True)



# Load all cogs except legacy_gambling.py
for filename in os.listdir(COG_FOLDER):
    if filename.endswith('.py') and filename != 'legacy_gambling.py':
        client.load_extension(f'cogs.{filename[:-3]}')
# Ensure leaderboard cog is loaded (if not already in folder)
try:
    client.load_extension('cogs.leaderboard')
except Exception:
    pass

if __name__ == "__main__":
    client.run(TOKEN)
