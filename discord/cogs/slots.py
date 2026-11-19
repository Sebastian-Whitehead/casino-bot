import asyncio
import bisect
import io
import logging
import os
import random

import nextcord as discord
from nextcord import ui, Interaction, ButtonStyle
from nextcord.ext import commands
from PIL import Image

from modules.base_betting_view import BaseBettingView
from modules.economy import Economy
from modules.base_game_cog import BaseGameCog, Outcome
from modules.game_ui import GameResultView, format_chips, safe_edit, safe_send
from modules.helpers import SLOTS_DEFAULT_BET, SLOTS_MULTS, SLOTS_WIN_RATE, GUILD_KW, make_embed, payout

AUTO_SPIN_DELAY = 5
SYMBOLS = ["Lemon", "Seven", "Diamond", "Coin", "Bell", "Cherry"]  # index = reel_symbols() value = SLOTS_MULTS index


def paytable_embed(bet):
    rows = sorted(range(len(SLOTS_MULTS)), key=lambda i: -SLOTS_MULTS[i])
    lines = [f"{SYMBOLS[i]} x3: {SLOTS_MULTS[i]}x = {format_chips(payout(bet, SLOTS_MULTS[i]))}" for i in rows]
    return make_embed(title="Slots paytable",
                      description=f"Three matching symbols win. Payouts for a {format_chips(bet)} bet:\n" + "\n".join(lines))
log = logging.getLogger(__name__)


ASSETS = os.path.join(os.path.dirname(__file__), '..', 'modules')
ITEM = 180  # height of one symbol on the reel strip
_images = {}


def _image(name):
    if name not in _images:
        _images[name] = Image.open(f'{ASSETS}/{name}').convert('RGBA')
    return _images[name]


def pick_reels(rng=random):
    """Three reel stops. A small chance of a forced weighted win; otherwise the reels are independent."""
    items = _image('slot-reel.png').size[1] // ITEM
    s = [rng.randint(1, items - 1) for _ in range(3)]
    if rng.random() < SLOTS_WIN_RATE:
        pos = bisect.bisect([3.5, 7, 15, 25, 55], round(rng.random() * 100, 1))
        s = [pos + rng.randint(1, int(items / 6 - 1)) * 6 for _ in range(3)]
        s = [x - 6 if x == items else x for x in s]
    return s


def reel_symbols(*stops):
    """Symbol 0-5 shown on each reel (index into SLOTS_MULTS)."""
    return tuple((1 + x) % 6 for x in stops)


def render_spin(s1, s2, s3) -> io.BytesIO:
    facade, reel = _image('slot-face.png'), _image('slot-reel.png')
    rw = reel.size[0]
    speed = 6
    images = []
    for i in range(1, ITEM // speed + 1):
        bg = Image.new('RGBA', facade.size, color=(255, 255, 255))
        for n, stop in enumerate((s1, s2, s3)):
            bg.paste(reel, (25 + rw * n, 100 - speed * i * stop))
        bg.alpha_composite(facade)
        images.append(bg)
    buf = io.BytesIO()  # in memory: no temp file to leak
    images[0].save(buf, format='GIF', save_all=True, append_images=images[1:], duration=50)
    buf.seek(0)
    return buf


class _AutoInteraction:
    """Stand-in for auto-spins: no interaction is alive, so nothing may be sent through it."""

    class response:
        @staticmethod
        def is_done():
            return True


class BettingView(BaseBettingView):
    def __init__(self, cog, user, bet, thread):
        super().__init__(cog, user, bet, thread)
        self.auto_spin = False
        self.auto_task = None
        self.in_round = False  # a spin is running: ignore extra Start clicks
        self._auto_stop_event = asyncio.Event()

    @ui.button(label="Auto", style=ButtonStyle.secondary, row=2, custom_id="slots_auto_spin")
    async def auto_spin_btn(self, button, interaction: Interaction):
        if self.auto_spin:
            self.stop_auto()
        else:
            self.auto_spin = True
            button.style = ButtonStyle.primary
            self._auto_stop_event.clear()
            self.auto_task = asyncio.create_task(self.auto_spin_loop())
        await interaction.response.edit_message(view=self)

    @ui.button(label="Paytable", style=ButtonStyle.secondary, row=2, custom_id="slots_paytable")
    async def show_paytable(self, button, interaction: Interaction):
        await interaction.response.send_message(embed=paytable_embed(self.bet), ephemeral=True)

    @ui.button(label="Start", style=ButtonStyle.success, row=2, custom_id="slots_start")
    async def start_spin(self, button, interaction: Interaction):
        await self.cog.start_round(self, interaction)

    def stop_auto(self):
        # Never cancel the task: it may be between placing the bet and paying out.
        self.auto_spin = False
        self._auto_stop_event.set()
        self.auto_spin_btn.style = ButtonStyle.secondary

    def _game_alive(self):
        return self.cog.active_games.get(self.thread.id) is self

    async def auto_spin_loop(self):
        try:
            spun = False
            while self.auto_spin and self._game_alive():
                try:
                    await asyncio.wait_for(self._auto_stop_event.wait(), timeout=AUTO_SPIN_DELAY)
                    break
                except asyncio.TimeoutError:
                    pass
                # Back to Bet clears game_message: that is the stop signal after a spin
                if not (self.auto_spin and self._game_alive()) or (spun and self.game_message is None):
                    break
                if self.get_balance() < self.bet:
                    await safe_send(self.thread, content=f"Auto-spin stopped: you need {format_chips(self.bet)} to spin "
                                                         f"(you have {format_chips(self.get_balance())}).")
                    break
                await self.cog.start_round(self, _AutoInteraction(), confirmed=True)
                spun = True
        except Exception as e:
            log.error("[Slots] Auto-spin error: %r", e)
        finally:
            self.stop_auto()
            self.auto_task = None
            if self._game_alive():
                await self.refresh_bet_message()


class Slots(BaseGameCog, commands.Cog):
    game_name = "Slots"

    def __init__(self, client: commands.Bot):
        self.client = client
        self.economy = Economy()
        self.active_games = {}  # {thread_id: BettingView}
        self.default_bet = SLOTS_DEFAULT_BET

    @discord.slash_command(
        description="Play the slot machine. Three matching symbols win.",
        **GUILD_KW
    )
    async def slots(self, interaction: discord.Interaction):
        await self.open_game(interaction, BettingView)

    @discord.slash_command(description="Show what each slots symbol pays.", **GUILD_KW)
    async def slots_paytable(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=paytable_embed(self.default_bet), ephemeral=True)

    async def start_round(self, betting_view, interaction, confirmed=False, **choice):
        if betting_view.in_round:
            if not interaction.response.is_done():
                await interaction.response.defer()
            return
        betting_view.in_round = True
        try:
            await super().start_round(betting_view, interaction, confirmed, **choice)
        finally:
            betting_view.in_round = False

    async def play(self, betting_view, interaction, **choice) -> Outcome:
        bet = betting_view.bet
        s1, s2, s3 = pick_reels()
        # GIF building is CPU-heavy: keep it off the event loop so other commands stay responsive
        buf = await asyncio.to_thread(render_spin, s1, s2, s3)
        file = discord.File(buf, filename=f'{betting_view.user.id}_slots.gif')
        symbols = reel_symbols(s1, s2, s3)
        if symbols[0] == symbols[1] == symbols[2]:
            return Outcome(True, payout(bet, SLOTS_MULTS[symbols[0]]), "Slots: three of a kind!",
                           file=file)
        return Outcome(False, 0, "Slots: no match", file=file)


def setup(client: commands.Bot):
    client.add_cog(Slots(client))
