import os
import re
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("ECONOMY_DB_PATH", os.path.join(tempfile.mkdtemp(), "e.db"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "discord"))
_cwd = os.getcwd()
from modules import embed_processor as ep  # noqa: E402
from modules import helpers  # noqa: E402
from modules.challenge import ChallengeGameCog, ChallengeView  # noqa: E402
os.chdir(_cwd)

# every placeholder the code supplies; embeds/*.json may only use these (or the generic ones)
SUPPLIED = {"game", "bet", "result", "payout", "fee_line", "roll", "winner_roll", "loser_roll", "wallet", "choice_line"}
for _n in ("challenger", "opponent", "winner", "loser", "user"):
    SUPPLIED |= {_n, _n + "_name", _n + "_id"}
GENERIC = re.compile(r"\{(?:channel|setting):[\w\-]+\}")


def member(i, name):
    return SimpleNamespace(id=i, mention=f"<@{i}>", display_name=name)


class EmbedFileTests(unittest.TestCase):
    def files(self):
        return sorted(p.stem for p in ep.EMBEDS_DIR.glob("*.json"))

    def test_every_file_is_valid_and_only_uses_supplied_placeholders(self):
        self.assertTrue(self.files())
        for key in self.files():
            data = ep.EmbedProcessor.load_embed_data(key)
            self.assertTrue(data.get("embeds"), key)
            text = repr(data)
            used = set(re.findall(r"\{(\w+)\}", GENERIC.sub("", text)))
            self.assertLessEqual(used, SUPPLIED, f"{key}: unknown placeholder {used - SUPPLIED}")

    def test_render_leaves_no_placeholders(self):
        repl = {f"{{{n}}}": "x" for n in SUPPLIED}
        for key in self.files():
            msg = ep.render_embed(key, repl)
            self.assertTrue(msg["embeds"][0].title and msg["embeds"][0].description, key)
            self.assertFalse(re.search(r"\{\w+\}", repr([e.to_dict() for e in msg["embeds"]]) + str(msg["content"])), key)

    def test_generic_placeholders_and_unknown_stay_literal(self):
        out = ep.EmbedProcessor.replace_placeholders(
            "{channel:casino} {setting:chip_value} {nope} {setting:missing}", {})
        self.assertIn(f"<#{helpers.CASINO_CHANNEL_ID}>", out)
        self.assertIn(str(helpers.config.get("chip_value", "")), out)
        self.assertIn("{nope}", out)
        self.assertIn("{setting:missing}", out)

    def test_missing_file_is_loud(self):
        with self.assertRaises(FileNotFoundError):
            ep.render_embed("nope")


class ChallengeExpiryTests(unittest.IsolatedAsyncioTestCase):
    async def test_challenge_pings_opponent_through_content(self):
        view = ChallengeView(None, member(1, "A"), member(2, "B"), 5, None, "Coin Flip")
        msg = ep.render_embed("challenge", view.replacements())
        self.assertEqual(msg["content"], "<@2>")
        self.assertIn("5 chips", msg["embeds"][0].description)
        # files without content must clear it on edit
        self.assertIsNone(ep.render_embed("challenge_accepted", view.replacements())["content"])

    async def test_timeout_edits_message_once(self):
        view = ChallengeView(None, member(1, "A"), member(2, "B"), 5, None, "Coin Flip")
        view.challenge_message = mock.AsyncMock()
        await view.on_timeout()
        await view.on_timeout()  # a second call must not edit again
        self.assertEqual(view.challenge_message.edit.await_count, 1)
        self.assertTrue(view.resolved)


class ChannelRestrictionTests(unittest.IsolatedAsyncioTestCase):
    async def test_challenge_outside_casino_channel_is_rejected(self):
        cog = ChallengeGameCog()
        cog.economy = mock.Mock()
        inter = SimpleNamespace(
            user=SimpleNamespace(id=1), channel=SimpleNamespace(id=helpers.CASINO_CHANNEL_ID + 1),
            response=SimpleNamespace(send_message=mock.AsyncMock()))
        with mock.patch.object(helpers, "RESTRICT_TO_CASINO_CHANNEL", True):
            result = await cog.open_challenge(inter, SimpleNamespace(id=2, bot=False), 5, "Coin Flip")
        self.assertIsNone(result)
        self.assertIn("casino channel", inter.response.send_message.await_args.args[0])
        cog.economy.get_chips.assert_not_called()

    async def test_helper_allows_casino_channel_and_unrestricted(self):
        from modules.game_ui import ensure_casino_channel

        def inter(cid):
            return SimpleNamespace(channel=SimpleNamespace(id=cid),
                                   response=SimpleNamespace(send_message=mock.AsyncMock()))
        ok, elsewhere, free = (inter(helpers.CASINO_CHANNEL_ID), inter(helpers.CASINO_CHANNEL_ID + 1),
                               inter(helpers.CASINO_CHANNEL_ID + 1))
        with mock.patch.object(helpers, "RESTRICT_TO_CASINO_CHANNEL", True):
            self.assertTrue(await ensure_casino_channel(ok))
            self.assertFalse(await ensure_casino_channel(elsewhere))
        elsewhere.response.send_message.assert_awaited_once()
        ok.response.send_message.assert_not_awaited()
        with mock.patch.object(helpers, "RESTRICT_TO_CASINO_CHANNEL", False):
            self.assertTrue(await ensure_casino_channel(free))


if __name__ == "__main__":
    unittest.main()
