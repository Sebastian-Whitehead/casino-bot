import asyncio
import os
import sys
import tempfile
import unittest
from collections import Counter
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("ECONOMY_DB_PATH", os.path.join(tempfile.mkdtemp(), "t.db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "discord"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.base_betting_view import BaseBettingView  # noqa: E402
from modules.base_game_cog import BaseGameCog, Outcome  # noqa: E402
from modules.game_ui import GameResultView, format_chips  # noqa: E402
from modules import helpers  # noqa: E402
from fakes import FakeEconomy  # noqa: E402


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
    def setUp(self):
        p = patch.object(helpers, "CONFIRM_BETS", False)  # confirmation is tested separately
        p.start()
        self.addCleanup(p.stop)

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

    async def test_half_and_all_in_buttons(self):
        v = FakeView(FakeGame(100, True), SimpleNamespace(id=1), 5, MagicMock())
        i = make_interaction()
        i.response.edit_message = AsyncMock()
        await v.bet_max.callback(i)
        self.assertEqual(v.bet, 100)
        await v.bet_half.callback(i)
        self.assertEqual(v.bet, 50)

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
        self.assertFalse(await cog.validate_wager(view, i))
        self.assertIn("/cashier", i.response.send_message.call_args[0][0])
        self.assertEqual(cog.economy.chips[1], 1)

    async def test_play_error_refunds_the_wager(self):
        cog = FakeGame(100, True)
        view = await cog.open_game(make_interaction(), FakeView)
        with patch.object(FakeGame, "play", AsyncMock(side_effect=RuntimeError("boom"))):
            with self.assertRaises(RuntimeError):
                await cog.start_round(view, make_interaction(), pick="x")
        self.assertEqual(cog.economy.chips[1], 100)
        self.assertEqual(cog.economy.open_count(), 0)

    async def test_settle_pays_once_per_game_id(self):
        cog = await self._run(True)
        view = cog.active_games[99]
        game_id = view.game_id
        await cog.settle(view, Outcome(True, 20, "again"), {}, game_id)  # a retry for the same game
        self.assertEqual(cog.economy.chips[1], 110)

    async def test_each_round_gets_its_own_game_id(self):
        cog = FakeGame(100, True)
        view = await cog.open_game(make_interaction(), FakeView)
        await cog.start_round(view, make_interaction(), pick="x")
        first = view.game_id
        await cog.start_round(view, make_interaction(), pick="x")
        self.assertNotEqual(first, view.game_id)
        self.assertEqual(len(cog.economy.wagers), 2)

    async def test_end_game_by_thread(self):
        cog = FakeGame(100, True)
        view = await cog.open_game(make_interaction(), FakeView)
        await cog.end_game_by_thread(99)
        self.assertNotIn(99, cog.active_games)


if __name__ == "__main__":
    unittest.main()


class ConfirmTests(unittest.IsolatedAsyncioTestCase):
    """Step 2: nothing is withdrawn until the player confirms."""

    async def _begin(self, press):
        cog = FakeGame(100, True)
        view = FakeView(cog, SimpleNamespace(id=1, mention="<@1>", display_name="p"), 10, MagicMock())
        view.refresh_bet_message = AsyncMock()
        first = make_interaction()
        press_inter = make_interaction()
        press_inter.user = SimpleNamespace(id=1)
        task = asyncio.ensure_future(cog.begin_wager(view, first, {"pick": "x"}))
        for _ in range(20):
            await asyncio.sleep(0)
            if first.response.send_message.await_count:
                break
        prompt = first.response.send_message.await_args.kwargs["view"]
        self.assertEqual(cog.economy.chips[1], 100)  # still nothing taken at the prompt
        press_inter.response.edit_message = AsyncMock()
        await getattr(prompt, press).callback(press_inter)
        return cog, view, await task, press_inter

    async def test_confirm_withdraws_by_game_id(self):
        with patch.object(helpers, "CONFIRM_BETS", True):
            cog, view, started, press_inter = await self._begin("confirm")
        game_id, interaction = started
        self.assertIs(interaction, press_inter)
        self.assertEqual(view.game_id, game_id)
        self.assertEqual(cog.economy.chips[1], 90)
        self.assertEqual(cog.economy.wagers[(game_id, 1)]["status"], "open")

    async def test_bet_changed_during_prompt_uses_the_confirmed_amount(self):
        with patch.object(helpers, "CONFIRM_BETS", True):
            cog = FakeGame(100, True)
            view = FakeView(cog, SimpleNamespace(id=1, mention="<@1>", display_name="p"), 10, MagicMock())
            view.refresh_bet_message = AsyncMock()
            first, press = make_interaction(), make_interaction()
            press.user = SimpleNamespace(id=1)
            press.response.edit_message = AsyncMock()
            task = asyncio.ensure_future(cog.begin_wager(view, first, {}))
            for _ in range(20):
                await asyncio.sleep(0)
                if first.response.send_message.await_count:
                    break
            view.bet = 50  # player presses x10 after the prompt opened
            await first.response.send_message.await_args.kwargs["view"].confirm.callback(press)
            game_id, _ = await task
        self.assertEqual(cog.economy.wagers[(game_id, 1)]["amount"], 10)
        self.assertEqual(view.bet, 10)

    async def test_cancel_takes_nothing(self):
        with patch.object(helpers, "CONFIRM_BETS", True):
            cog, view, started, _ = await self._begin("cancel")
        self.assertIsNone(started)
        self.assertEqual(cog.economy.chips[1], 100)
        self.assertEqual(cog.economy.wagers, {})

    async def test_confirmed_replay_skips_the_prompt(self):
        cog = FakeGame(100, True)
        view = FakeView(cog, SimpleNamespace(id=1), 10, MagicMock())
        view.refresh_bet_message = AsyncMock()
        i = make_interaction()
        with patch.object(helpers, "CONFIRM_BETS", True):
            started = await cog.begin_wager(view, i, {}, confirmed=True)
        self.assertIsNotNone(started)
        i.response.send_message.assert_not_awaited()
