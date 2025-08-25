# --- Auto-delete dormant threads in a specific channel ---
ENABLE_AUTO_THREAD_CLEANUP = True  # Toggle this to enable/disable auto thread cleanup
from modules.auto_thread_cleanup import setup_auto_thread_cleanup, run_thread_cleanup





# Use nextcord instead of discord.py for compatibility with your error
import nextcord as discord
from nextcord.ext import commands
from modules.helpers import *



# Explicitly set only the privileged intents you need
intents = discord.Intents.default()
intents.members = True
intents.message_content = True  # Enable if your bot needs to read message content

client = commands.Bot(
    command_prefix=PREFIX,
    owner_ids=OWNER_IDS,
    intents=intents,
    help_command=None
)

# Global event handler for thread deletions
@client.event
async def on_thread_delete(thread):
    parent = getattr(thread, 'parent', None)
    parent_name = getattr(parent, 'name', None) if parent else None
    print(f"[Thread Delete] '{thread.name}' (ID: {thread.id}) deleted in channel: {parent_name}")

from modules.helpers import TEST_GUILD_ID
USE_TEST_GUILD = True  # Set to True for fast test registration

@client.event
async def on_ready():
    print(f'Logged in as {client.user}')
    # Start background task for auto-deleting dormant threads
    if ENABLE_AUTO_THREAD_CLEANUP:
        setup_auto_thread_cleanup(client)

def _is_owner(interaction):
    return interaction.user.id in OWNER_IDS

async def handle_cleanup_command(interaction):
    if not _is_owner(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    try:
        await interaction.response.defer(ephemeral=True)
        await run_thread_cleanup(client)
        await interaction.followup.send("Thread cleanup triggered.", ephemeral=True)
    except Exception as e:
        print(f"[Cleanup Command] Error: {e}")
        # import traceback; print(traceback.format_exc())  # Stack trace commented for cleaner logs

@client.slash_command(
    description="Manually trigger thread cleanup (owner only)",
    **({"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {})
)
async def cleanup_threads(interaction: discord.Interaction):
    if not _is_owner(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    await handle_cleanup_command(interaction)


# --- Simple in-memory casino balance variable ---
CASINO_BALANCE = 100000

@client.slash_command(
    description="Show the casino's current balance (owner only)",
    **({"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {})
)
async def casino_balance(interaction: discord.Interaction):
    if not _is_owner(interaction):
        await interaction.response.send_message("You do not have permission to use this command.", ephemeral=True)
        return
    global CASINO_BALANCE
    await interaction.response.send_message(f"Casino balance: ${CASINO_BALANCE}", ephemeral=True)


# Load all cogs except legacy_gambling.py
for filename in os.listdir(COG_FOLDER):
    if filename.endswith('.py') and filename != 'legacy_gambling.py':
        client.load_extension(f'cogs.{filename[:-3]}')

if __name__ == "__main__":
    client.run(TOKEN)
