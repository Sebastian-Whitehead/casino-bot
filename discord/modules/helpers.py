import os
from datetime import datetime
from pathlib import Path

import yaml
from nextcord import Color, Embed

# --- Load config before using it ---
os.chdir(Path(__file__).parent.parent)
ABS_PATH = Path(os.getcwd())
COG_FOLDER = os.path.join(ABS_PATH, 'cogs/')


with open(os.path.join(ABS_PATH.parent, 'config.yml'),  # type:ignore
            'r', encoding='utf-8') as f:
    config_raw = yaml.safe_load(f.read())
    config = config_raw.get('bot', {})

# Casino balance tracking toggle
TRACK_CASINO_BALANCE = config.get('track_casino_balance', True)

# Test guild and casino channel config
TEST_GUILD_ID = config.get('test_guild_id')
CASINO_CHANNEL_ID = config.get('casino_channel_id')
import os
from datetime import datetime
from pathlib import Path

import yaml
from nextcord import Color, Embed


class InsufficientFundsException(Exception):
    def __init__(self, current, bet) -> None:
        self.needs = bet - current
        super().__init__()

    def __str__(self) -> str:
        return f"${self.needs} more needed to play."

os.chdir(Path(__file__).parent.parent)
ABS_PATH = Path(os.getcwd())
COG_FOLDER = os.path.join(ABS_PATH, 'cogs/')



with open(os.path.join(ABS_PATH.parent, 'config.yml'),  # type:ignore
            'r', encoding='utf-8') as f:
    config_raw = yaml.safe_load(f.read())
    # print('Loaded config.yml:', config_raw)  # Commented for less noisy startup
    config = config_raw.get('bot', {})


# Expose thread cleanup config for import elsewhere
THREAD_TIMEOUT_MINUTES = config_raw.get('thread_timeout_minutes', 60)
THREAD_CLEANUP_CHECK_SECONDS = config_raw.get('thread_cleanup_check_seconds', 60)

COINFLIP_MULT = config.get('coinflip_multiplier', 2)
BLACKJACK_MULT = config.get('blackjack_multiplier', 2)
BLACKJACK_BJ_MULT = config.get('blackjack_blackjack_multiplier', 2.5)
SLOTS_MULTS = config.get('slots_multipliers', [4, 80, 40, 25, 10, 5])
B_MULT = config.get('bonus_multiplier', 5)
DICE_MULT = config.get('dice_multiplier', 5)
TOKEN = config.get('token')
PREFIX = config.get('prefix', '$')
OWNER_IDS = config.get('owner_ids')
DEFAULT_BET = config.get('default_bet', 100)
SLOTS_DEFAULT_BET = config.get('slots_default_bet', 1)
TOKEN_PRICE = config.get('token_price', 10)
B_COOLDOWN = config.get('bonus_cooldown', 12)
CASINO_USER_ID = config.get('casino_user_id', 0)
RESTRICT_TO_CASINO_CHANNEL = config.get('restrict_to_casino_channel', True)
CHALLENGE_FEE_ENABLED = config.get('challenge_fee_enabled', True)
CHALLENGE_FEE_PERCENT = config.get('challenge_fee_percent', 5)
# print('Loaded bot config:', config)  # Commented for less noisy startup
# print('PREFIX:', PREFIX)



def make_embed(title=None, description=None, color=None, author=None,
               image=None, link=None, footer=None) -> Embed:
    """Wrapper for making discord embeds"""
    # Only set description if provided, to avoid <property object ...>
    embed_kwargs = {}
    if title:
        embed_kwargs['title'] = title
    if description:
        embed_kwargs['description'] = description
    if color:
        embed_kwargs['color'] = color
    else:
        embed_kwargs['color'] = Color.random()
    if link:
        embed_kwargs['url'] = link
    embed = Embed(**embed_kwargs)
    if author:
        embed.set_author(name=author)
    if image:
        embed.set_image(url=image)
    # Only set footer if it's a valid string and not a property object
    from nextcord import Embed as _Embed
    if footer is not None and not isinstance(footer, property) and footer != _Embed.Empty:
        embed.set_footer(text=str(footer))
    else:
        embed.set_footer(text=datetime.now().strftime("%m/%d/%Y %H:%M:%S"))
    return embed
