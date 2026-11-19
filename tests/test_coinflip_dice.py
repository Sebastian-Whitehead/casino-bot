import os
import sys
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest import mock

_tmp = tempfile.mkdtemp()
os.environ["ECONOMY_DB_PATH"] = os.path.join(_tmp, "test.db")  # before importing economy
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "discord"))

from modules import helpers  # noqa: E402
from modules.economy import Economy  # noqa: E402
from modules import challenge as challenge_mod  # noqa: E402
from cogs import coinflip, roller  # noqa: E402

CASINO = helpers.CASINO_USER_ID


def make_cog(cls):
    cog = cls(mock.Mock())
    cog.economy = Economy()
    return cog


def user(uid, chips):
    eco = Economy()
    eco.get_entry(uid)
    eco.set_credits(uid, chips)
    return SimpleNamespace(id=uid, bot=False, mention=f"<@{uid}>", display_name=str(uid))


class ViewIds(unittest.IsolatedAsyncioTestCase):
    def assert_unique(self, view):
        ids = [c.custom_id for c in view.children]
        self.assertEqual(len(ids), len(set(ids)), ids)

    async def test_custom_ids_unique(self):
        u = user(1001, 50)
        self.assert_unique(coinflip.CoinFlipBettingView(make_cog(coinflip.CoinFlip), u, 5, None))
        self.assert_unique(roller.RollerBettingView(make_cog(roller.Roller), u, 5, None))
        self.assert_unique(challenge_mod.ChallengeView(None, u, u, 5, None, "x"))

    async def test_dice_has_six_guesses_and_one_close(self):
        view = roller.RollerBettingView(make_cog(roller.Roller), user(1002, 50), 5, None)
        ids = [c.custom_id for c in view.children]
        self.assertEqual([i for i in ids if i.startswith("dice_guess_")],
                         [f"dice_guess_{n}" for n in range(1, 7)])
        self.assertEqual(ids.count("close"), 1)

    def test_coinflip_min_bet(self):
        self.assertEqual(coinflip.CoinFlipBettingView.min_bet, helpers.COINFLIP_MIN_BET)


class Challenge(unittest.TestCase):
    def setUp(self):
        self.cog = make_cog(coinflip.CoinFlip)
        self.eco = self.cog.economy

    def _stake(self, a, b, bet):
        """Open both wagers under one game id; returns a challenge-like object."""
        game_id = uuid.uuid4().hex
        for u in (a, b):
            self.eco.open_wager(game_id, u.id, "Coin Flip", bet)
        return SimpleNamespace(challenger=a, opponent=b, bet=bet, game_id=game_id)

    def _fee(self, pot_bet, pct):
        with mock.patch.object(challenge_mod, "CHALLENGE_FEE_ENABLED", True), \
             mock.patch.object(challenge_mod, "CHALLENGE_FEE_PERCENT", pct):
            a, b = user(2001, 1000), user(2002, 1000)
            ch = self._stake(a, b, pot_bet)
            before = self.eco.get_chips(a.id)
            paid, fee = self.cog.settle_challenge(ch, a, b)
            self.assertEqual(self.eco.get_chips(a.id) - before, paid)
            self.assertEqual(paid + fee, pot_bet * 2)
            return paid, fee

    def test_fee_floors(self):
        self.assertEqual(self._fee(5, 5), (10, 0))     # pot 10 -> 0.5 floors to 0
        self.assertEqual(self._fee(50, 5), (95, 5))    # pot 100 -> 5
        self.assertEqual(self._fee(11, 5), (21, 1))    # pot 22 -> 1.1 floors to 1

    def test_fee_stays_with_casino(self):
        with mock.patch.object(challenge_mod, "CHALLENGE_FEE_ENABLED", True), \
             mock.patch.object(challenge_mod, "CHALLENGE_FEE_PERCENT", 5):
            a, b = user(2003, 100), user(2004, 100)
            total = sum(self.eco.get_chips(x) for x in (a.id, b.id, CASINO))
            ch = self._stake(a, b, 50)
            self.cog.settle_challenge(ch, a, b)
            self.assertEqual(sum(self.eco.get_chips(x) for x in (a.id, b.id, CASINO)), total)

    def test_refund_pays_both_back(self):
        a, b = user(2005, 30), user(2006, 40)
        ch = self._stake(a, b, 10)
        self.cog.refund_challenge(ch)
        self.assertEqual((self.eco.get_chips(a.id), self.eco.get_chips(b.id)), (30, 40))
        self.cog.refund_challenge(ch)  # a second refund must not pay again
        self.assertEqual((self.eco.get_chips(a.id), self.eco.get_chips(b.id)), (30, 40))


class Solo(unittest.IsolatedAsyncioTestCase):
    async def test_coinflip_payout(self):
        cog = make_cog(coinflip.CoinFlip)
        view = SimpleNamespace(bet=7)
        with mock.patch.object(coinflip.random, "choice", return_value="heads"):
            win = await cog.play(view, None, user_choice="heads")
            loss = await cog.play(view, None, user_choice="tails")
        self.assertTrue(win.won)
        self.assertEqual(win.payout, helpers.payout(7, helpers.COINFLIP_MULT))
        self.assertEqual((loss.won, loss.payout), (False, 0))
        self.assertEqual(win.file.filename, "cf-heads.gif")

    async def test_dice_payout(self):
        cog = make_cog(roller.Roller)
        view = SimpleNamespace(bet=3)
        with mock.patch.object(roller.random, "randint", return_value=4):
            win = await cog.play(view, None, guess=4)
            loss = await cog.play(view, None, guess=2)
        self.assertEqual(win.payout, helpers.payout(3, helpers.DICE_MULT))
        self.assertEqual((loss.won, loss.payout), (False, 0))


if __name__ == "__main__":
    unittest.main()
