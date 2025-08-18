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
    print('Loaded config.yml:', config_raw)
    config = config_raw.get('bot', {})

TOKEN = config.get('token')
PREFIX = config.get('prefix', '$')
OWNER_IDS = config.get('owner_ids')
DEFAULT_BET = config.get('default_bet', 100)
B_MULT = config.get('bonus_multiplier', 5)
B_COOLDOWN = config.get('bonus_cooldown', 12)
print('Loaded bot config:', config)
print('PREFIX:', PREFIX)


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
