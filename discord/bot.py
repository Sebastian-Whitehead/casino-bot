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

USE_TEST_GUILD = True  # Set to True for fast test registration
GUILD_KW = {"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {}

@client.event
async def on_ready() -> None:
    """Bot startup event."""
    logger.info(f'Logged in as {client.user}')
    Economy().bind_casino_user(client.user.id)
    if TEST_MODE:
        logger.warning('TEST MODE is ON: every player has infinite bank money. Turn off test_mode in config.yml for real play.')
    refunded = Economy().refund_open_wagers()  # games from the previous run died with it
    if refunded:
        logger.info(f'Refunded {refunded} open wager(s) left by the previous run')
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
        deleted = await run_thread_cleanup(client)
        await interaction.followup.send(f"Thread cleanup done: deleted {deleted} thread(s).", ephemeral=True)
    except Exception as e:
        logger.error(f"[Cleanup Command] Error: {e}")

@client.slash_command(
    description="Manually trigger thread cleanup (owner only)",
    **GUILD_KW
)
async def cleanup_threads(interaction: discord.Interaction) -> None:
    """Slash command to manually trigger thread cleanup (owner only)."""
    await handle_cleanup_command(interaction)




# --- Casino balance command (DB-backed) ---
from modules.economy import Economy


@client.slash_command(
    description="Show the casino's current balance (owner only)",
    **GUILD_KW
)
async def casino_balance(interaction: discord.Interaction) -> None:
    """Slash command to show the casino's current balance (owner only)."""
    if not _is_owner(interaction):
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return
    if not TRACK_CASINO_BALANCE:
        await interaction.response.send_message("Casino balance tracking is disabled in config.", ephemeral=True)
        return
    econ = Economy()
    await interaction.response.send_message(
        f"Casino bank: ${econ.bank.balance(econ.casino_user_id):,}\n"
        f"Casino chips: {econ.get_chips(econ.casino_user_id):,}", ephemeral=True)


# --- Add money to casino (owner only) ---
@client.slash_command(
    description="Add money to the casino's balance (owner only)",
    **GUILD_KW
)
async def add_casino_money(interaction: discord.Interaction, amount: int) -> None:
    """Slash command to add money to the casino's balance (owner only)."""
    if not _is_owner(interaction):
        await interaction.response.send_message("❌ You do not have permission to use this command.", ephemeral=True)
        return
    if not TRACK_CASINO_BALANCE:
        await interaction.response.send_message("Casino balance tracking is disabled in config.", ephemeral=True)
        return
    if amount == 0:
        await interaction.response.send_message("Amount must not be zero.", ephemeral=True)
        return
    econ = Economy()
    cid = econ.casino_user_id
    econ.bank.set_balance(cid, econ.bank.balance(cid) + amount)
    await interaction.response.send_message(
        f"Added ${amount} to the casino bank. New balance: ${econ.bank.balance(cid):,}", ephemeral=True)



# Load all cogs
for filename in os.listdir(COG_FOLDER):
    if filename.endswith('.py'):
        client.load_extension(f'cogs.{filename[:-3]}')
# Ensure leaderboard cog is loaded (if not already in folder)
#try:
#    client.load_extension('cogs.leaderboard')
#except Exception:
#    pass

if __name__ == "__main__":
    client.run(TOKEN)
