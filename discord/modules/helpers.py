import math
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
        return f"{self.needs} more needed to play."


os.chdir(Path(__file__).parent.parent)
ABS_PATH = Path(os.getcwd())
COG_FOLDER = os.path.join(ABS_PATH, 'cogs/')

with open(os.path.join(ABS_PATH.parent, 'config.yml'), encoding='utf-8') as f:
    config_raw = yaml.safe_load(f.read())
    config = config_raw.get('bot', {})

# DISCORD_TOKEN env var overrides the token in config.yml (handy for Docker)
TOKEN = os.environ.get('DISCORD_TOKEN') or config.get('token')

TRACK_CASINO_BALANCE = config.get('track_casino_balance', True)
TEST_GUILD_ID = config.get('test_guild_id')
USE_TEST_GUILD = True  # True: slash commands register per-guild (instant); False: global
GUILD_KW = {"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {}
CASINO_CHANNEL_ID = config.get('casino_channel_id')
THREAD_TIMEOUT_MINUTES = config_raw.get('thread_timeout_minutes', 60)
THREAD_CLEANUP_CHECK_SECONDS = config_raw.get('thread_cleanup_check_seconds', 60)

COINFLIP_MULT = config.get('coinflip_multiplier', 2)
BLACKJACK_MULT = config.get('blackjack_multiplier', 2)
BLACKJACK_BJ_MULT = config.get('blackjack_blackjack_multiplier', 2.5)
SLOTS_MULTS = config.get('slots_multipliers', [4, 80, 40, 25, 10, 5])
B_MULT = config.get('bonus_multiplier', 5)
DICE_MULT = config.get('dice_multiplier', 5)
PREFIX = config.get('prefix', '$')
OWNER_IDS = config.get('owner_ids')
DEFAULT_BET = config.get('default_bet', 1)  # chips
SLOTS_DEFAULT_BET = config.get('slots_default_bet', 1)  # chips
CHIP_VALUE = config.get('chip_value', 10)  # bank money per chip
COINFLIP_MIN_BET = config.get('coinflip_min_bet', 2)  # chips
B_COOLDOWN = config.get('bonus_cooldown', 12)
CASINO_USER_ID = config.get('casino_user_id', 0)
RESTRICT_TO_CASINO_CHANNEL = config.get('restrict_to_casino_channel', True)
CHALLENGE_FEE_ENABLED = config.get('challenge_fee_enabled', True)
CHALLENGE_FEE_PERCENT = config.get('challenge_fee_percent', 5)
CONFIRM_BETS = config.get('confirm_bets', True)
SLOTS_WIN_RATE = config.get('slots_win_rate', 0.03)  # chance of the forced-win branch; tuned so slots RTP is about 0.95
TEST_MODE = config.get('test_mode', False)  # infinite bank money; see config.yml.example


def payout(bet: int, mult) -> int:
    """Total chips returned (stake included) for a winning bet."""
    return int(math.floor(bet * mult))


def make_embed(title=None, description=None, color=None, author=None,
               image=None, link=None, footer=None) -> Embed:
    """Wrapper for making discord embeds"""
    # Only set description if provided, to avoid <property object ...>
    embed_kwargs = {'color': color or Color.random()}
    if title:
        embed_kwargs['title'] = title
    if description:
        embed_kwargs['description'] = description
    if link:
        embed_kwargs['url'] = link
    embed = Embed(**embed_kwargs)
    if author:
        embed.set_author(name=author)
    if image:
        embed.set_image(url=image)
    embed.set_footer(text=str(footer) if footer is not None else datetime.now().strftime("%m/%d/%Y %H:%M:%S"))
    return embed
