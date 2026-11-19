import os
import sys
import tempfile
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ECONOMY_DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "discord"))

from modules.card import Card  # noqa: E402
from modules import helpers  # noqa: E402
from cogs import blackjack as bj  # noqa: E402


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


def hand(*values):
    return [Card("spades", v) for v in values]


def make_cog(chips=100):
    cog = bj.Blackjack.__new__(bj.Blackjack)
    cog.economy = FakeEconomy(chips)
    cog.active_games = {}
    cog.default_bet = 10
    return cog


def make_game(cog, bet, player, dealer, deck=()):
    thread = SimpleNamespace(id=5, send=AsyncMock(), edit=AsyncMock())
    bv = bj.BettingView(cog, SimpleNamespace(id=1), bet, thread)
    cog.economy.place_bet(1, bet)
    bv.in_round = True
    bv.bet_in_play = bet
    gv = bj.GameView(cog, bv.user, bet, thread, list(deck), hand(*player), hand(*dealer), bv)
    return bv, gv


class CalcHand(unittest.TestCase):
    def test_values(self):
        c = bj.Blackjack.calc_hand
        self.assertEqual(c(hand(14, 13)), 21)       # blackjack
        self.assertEqual(c(hand(14, 14)), 12)       # two aces
        self.assertEqual(c(hand(14, 14, 9)), 21)
        self.assertEqual(c(hand(14, 13, 14)), 12)   # ace+king+ace
        self.assertEqual(c(hand(14, 5, 13)), 16)
        self.assertEqual(c(hand(10, 12, 5)), 25)    # bust
        down = hand(10, 7)
        down[1].flip()
        self.assertEqual(c(down), 10)               # face-down card ignored


class Payouts(unittest.IsolatedAsyncioTestCase):
    async def run_dealer(self, bet, player, dealer, deck=()):
        cog = make_cog()
        bv, gv = make_game(cog, bet, player, dealer, deck)
        gv.dealer_hand[1].flip()  # dealt face down
        with patch.object(bj.Blackjack, "render_file", return_value=MagicMock(filename="x.png")), \
                patch("modules.base_game_cog.safe_send", AsyncMock()), \
                patch.object(bv, "refresh_bet_message", AsyncMock()):
            await cog.dealer_play(gv)
        return cog, bv

    async def test_win(self):
        cog, bv = await self.run_dealer(10, (10, 9), (10, 7))
        self.assertEqual(cog.economy.chips[1], 90 + helpers.payout(10, helpers.BLACKJACK_MULT))
        self.assertFalse(bv.in_round)

    async def test_push(self):
        cog, _ = await self.run_dealer(10, (10, 8), (10, 8))
        self.assertEqual(cog.economy.chips[1], 100)

    async def test_loss(self):
        cog, _ = await self.run_dealer(10, (10, 7), (10, 9))
        self.assertEqual(cog.economy.chips[1], 90)
        self.assertEqual(cog.economy.chips["casino"], 10)

    async def test_blackjack(self):
        cog = make_cog()
        bv, gv = make_game(cog, 10, (14, 13), (10, 7))
        with patch.object(bj.Blackjack, "render_file", return_value=MagicMock(filename="x.png")), \
                patch("modules.base_game_cog.safe_send", AsyncMock()), \
                patch.object(bv, "refresh_bet_message", AsyncMock()):
            await cog.finish(gv, "Blackjack!", True, helpers.payout(10, helpers.BLACKJACK_BJ_MULT))
        self.assertEqual(cog.economy.chips[1], 90 + helpers.payout(10, helpers.BLACKJACK_BJ_MULT))

    async def test_double_start_blocked(self):
        cog = make_cog()
        bv = bj.BettingView(cog, SimpleNamespace(id=1), 10, MagicMock())
        bv.in_round = True
        inter = MagicMock()
        inter.response.is_done.return_value = False
        inter.response.defer = AsyncMock()
        await cog.start_round(bv, inter)
        self.assertEqual(cog.economy.chips[1], 100)  # nothing deducted


class CustomIds(unittest.IsolatedAsyncioTestCase):
    async def test_unique(self):
        cog = make_cog()
        bv, gv = make_game(cog, 10, (10, 5), (10, 7))
        for view in (bv, gv):
            ids = Counter(c.custom_id for c in view.children)
            self.assertEqual([k for k, v in ids.items() if v > 1], [])


if __name__ == "__main__":
    unittest.main()
