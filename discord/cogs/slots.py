import asyncio
import bisect
import io
import os
import random

import nextcord as discord
from nextcord import ui, Interaction, ButtonStyle
from nextcord.ext import commands
from PIL import Image

from modules.base_betting_view import BaseBettingView
from modules.base_game_cog import BaseGameCog, Outcome
from modules.game_ui import GameResultView, format_chips, safe_edit, safe_send
from modules.helpers import SLOTS_DEFAULT_BET, SLOTS_MULTS, TEST_GUILD_ID, payout

USE_TEST_GUILD = False  # Set to True for fast test registration
AUTO_SPIN_DELAY = 5


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
                await self.cog.start_round(self, _AutoInteraction())
                spun = True
        except Exception as e:
            print(f"[Slots] Auto-spin error: {e!r}")
        finally:
            self.stop_auto()
            self.auto_task = None
            if self._game_alive():
                await self.refresh_bet_message()


class Slots(BaseGameCog, commands.Cog):
    game_name = "Slots"

    def __init__(self, client: commands.Bot):
        self.client = client
        from modules.economy import Economy
        self.economy = Economy()
        self.active_games = {}  # {thread_id: BettingView}
        self.default_bet = SLOTS_DEFAULT_BET

    @discord.slash_command(
        description="Play the slot machine. Three matching symbols win.",
        **({"guild_ids": [TEST_GUILD_ID]} if USE_TEST_GUILD else {})
    )
    async def slots(self, interaction: discord.Interaction):
        await self.open_game(interaction, BettingView)

    async def play(self, betting_view, interaction, **choice) -> Outcome:
        bet = betting_view.bet
        path = os.path.join(os.path.dirname(__file__), '..', 'modules')
        facade = Image.open(f'{path}/slot-face.png').convert('RGBA')
        reel = Image.open(f'{path}/slot-reel.png').convert('RGBA')
        rw, rh = reel.size
        item = 180
        items = rh // item
        s1 = random.randint(1, items-1)
        s2 = random.randint(1, items-1)
        s3 = random.randint(1, items-1)
        win_rate = 12/100
        if random.random() < win_rate:
            symbols_weights = [3.5, 7, 15, 25, 55]
            x = round(random.random()*100, 1)
            pos = bisect.bisect(symbols_weights, x)
            s1 = pos + (random.randint(1, int((items/6)-1)) * 6)
            s2 = pos + (random.randint(1, int((items/6)-1)) * 6)
            s3 = pos + (random.randint(1, int((items/6)-1)) * 6)
            s1 = s1 - 6 if s1 == items else s1
            s2 = s2 - 6 if s2 == items else s2
            s3 = s3 - 6 if s3 == items else s3
        images = []
        speed = 6
        for i in range(1, (item//speed)+1):
            bg = Image.new('RGBA', facade.size, color=(255,255,255))
            bg.paste(reel, (25 + rw*0, 100-(speed * i * s1)))
            bg.paste(reel, (25 + rw*1, 100-(speed * i * s2)))
            bg.paste(reel, (25 + rw*2, 100-(speed * i * s3)))
            bg.alpha_composite(facade)
            images.append(bg)
        fp = f'{betting_view.user.id}_slots.gif'
        buf = io.BytesIO()  # in memory: no temp file to leak
        images[0].save(buf, format='GIF', save_all=True, append_images=images[1:], duration=50)
        buf.seek(0)
        file = discord.File(buf, filename=fp)
        # (1+s1)%6 gets the symbol 0-5 inclusive
        symbols = ((1+s1)%6, (1+s2)%6, (1+s3)%6)
        if symbols[0] == symbols[1] == symbols[2]:
            return Outcome(True, payout(bet, SLOTS_MULTS[symbols[0]]), "Slots: three of a kind!",
                           file=file)
        return Outcome(False, 0, "Slots: no match", file=file)


def setup(client: commands.Bot):
    client.add_cog(Slots(client))
