import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

_tmp = tempfile.mkdtemp()
os.environ["ECONOMY_DB_PATH"] = os.path.join(_tmp, "test.db")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "discord"))

from cogs import slots  # noqa: E402
from modules.helpers import SLOTS_MULTS  # noqa: E402


class FakeEconomy:
    def get_chips(self, user_id):
        return 100


class SlotsTest(unittest.IsolatedAsyncioTestCase):
    def _view(self, bet=3):
        cog = slots.Slots.__new__(slots.Slots)
        cog.economy = FakeEconomy()
        cog.active_games = {}
        view = slots.BettingView(cog, SimpleNamespace(id=1), bet, SimpleNamespace(id=2))
        return cog, view

    async def test_custom_ids_unique(self):
        _, view = self._view()
        from modules.game_ui import GameResultView
        result = GameResultView(None, view)
        ids = [c.custom_id for v in (view, result) for c in v.children]
        self.assertEqual(len(ids), len(set(ids)), ids)

    async def test_win_and_loss_payout(self):
        cog, view = self._view(3)
        with mock.patch.object(slots.random, "random", return_value=0.0), \
                mock.patch.object(slots.random, "randint", return_value=1):
            win = await cog.play(view, None)
        self.assertTrue(win.won)
        self.assertEqual(win.payout, int(3 * SLOTS_MULTS[1]))
        with mock.patch.object(slots.random, "random", return_value=0.99), \
                mock.patch.object(slots.random, "randint", side_effect=[1, 2, 3]):
            loss = await cog.play(view, None)
        self.assertFalse(loss.won)
        self.assertEqual(loss.payout, 0)


if __name__ == "__main__":
    unittest.main()
