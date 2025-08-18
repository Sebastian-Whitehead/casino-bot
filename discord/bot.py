
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
    intents=intents
)

client.remove_command('help')

for filename in os.listdir(COG_FOLDER):
    if filename.endswith('.py'):
        client.load_extension(f'cogs.{filename[:-3]}')

client.run(TOKEN)
