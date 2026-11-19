import os
import sys
import tempfile
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

os.environ.setdefault("ECONOMY_DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "discord"))

from modules.base_betting_view import BaseBettingView  # noqa: E402
from modules.base_game_cog import BaseGameCog, Outcome  # noqa: E402
from modules.game_ui import GameResultView, format_chips  # noqa: E402
from modules import helpers  # noqa: E402


class FakeEconomy:
    def __init__(self, chips):
        self.chips = {1: chips, "casino": 0}

    def get_chips(self, uid):
        return self.chips[uid]

    def place_bet(self, uid, n):
        assert n > 0 and self.chips[uid] >= n
        self.chips[uid] -= n
        self.chips["casino"] += n

    def pay_out(self, uid, n):
        self.chips["casino"] -= n
        self.chips[uid] += n


class FakeView(BaseBettingView):
    min_bet = 2


class FakeGame(BaseGameCog):
    game_name = "Fake"

    def __init__(self, chips, win):
        self.economy = FakeEconomy(chips)
        self.active_games = {}
        self.default_bet = 10
        self.win = win

    async def play(self, betting_view, interaction, **choice):
        return Outcome(self.win, betting_view.bet * 2 if self.win else 0, "Fake")


def make_interaction(done=False):
    i = MagicMock()
    i.user = SimpleNamespace(id=1, display_name="p")
    i.channel.id = helpers.CASINO_CHANNEL_ID
    thread = MagicMock(id=99)
    thread.send = AsyncMock(return_value=MagicMock(edit=AsyncMock(), delete=AsyncMock()))
    i.channel.create_thread = AsyncMock(return_value=thread)
    i.response.send_message = AsyncMock()
    i.response.defer = AsyncMock()
    i.response.is_done = MagicMock(return_value=done)
    return i


class ViewTests(unittest.IsolatedAsyncioTestCase):
    def test_format_chips(self):
        self.assertEqual(format_chips(1), "1 chip")
        self.assertEqual(format_chips(12), "12 chips")

    async def test_custom_ids_unique(self):
        cog = FakeGame(100, True)
        views = [FakeView(cog, SimpleNamespace(id=1), 5, MagicMock()),
                 GameResultView(cog, FakeView(cog, SimpleNamespace(id=1), 5, MagicMock()))]
        for v in views:
            ids = [c.custom_id for c in v.children]
            self.assertEqual([k for k, n in Counter(ids).items() if n > 1], [], type(v).__name__)

    async def test_cap_bet_uses_min_bet(self):
        v = FakeView(FakeGame(100, True), SimpleNamespace(id=1), 5, MagicMock())
        self.assertEqual(v.cap_bet(0), 2)
        self.assertEqual(v.cap_bet(1000), 100)

    async def _run(self, win):
        cog = FakeGame(100, win)
        i = make_interaction()
        view = await cog.open_game(i, FakeView)
        self.assertEqual(view.bet, 10)
        self.assertIn(99, cog.active_games)
        await cog.start_round(view, make_interaction(), pick="x")
        return cog

    async def test_flow_win(self):
        cog = await self._run(True)
        self.assertEqual(cog.economy.chips[1], 110)
        self.assertEqual(cog.economy.chips["casino"], -10)

    async def test_flow_loss(self):
        cog = await self._run(False)
        self.assertEqual(cog.economy.chips[1], 90)

    async def test_insufficient_mentions_cashier(self):
        cog = FakeGame(1, True)
        view = FakeView(cog, SimpleNamespace(id=1), 5, MagicMock())
        i = make_interaction()
        self.assertFalse(await cog.prepare_bet_round(view, i))
        self.assertIn("/cashier", i.response.send_message.call_args[0][0])
        self.assertEqual(cog.economy.chips[1], 1)

    async def test_end_game_by_thread(self):
        cog = FakeGame(100, True)
        view = await cog.open_game(make_interaction(), FakeView)
        await cog.end_game_by_thread(99)
        self.assertNotIn(99, cog.active_games)


if __name__ == "__main__":
    unittest.main()
