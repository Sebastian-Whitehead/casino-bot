import os
import random
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'discord'))
os.environ.setdefault('ECONOMY_DB_PATH', os.path.join(tempfile.mkdtemp(), 'slots.db'))

from modules.helpers import SLOTS_MULTS  # noqa: E402
from cogs import slots  # noqa: E402


class SlotsOddsTest(unittest.TestCase):
    def test_house_edge(self):
        """Seeded simulation: the player must lose money on average (RTP below 1)."""
        rng = random.Random(1)
        n = 100_000
        paid = 0
        for _ in range(n):
            sy = slots.reel_symbols(*slots.pick_reels(rng))
            if sy[0] == sy[1] == sy[2]:
                paid += SLOTS_MULTS[sy[0]]
        rtp = paid / n
        self.assertLess(rtp, 1.0, f"slots RTP is {rtp:.2f}")
        self.assertGreater(rtp, 0.8, f"slots RTP is {rtp:.2f}")

    def test_paytable_lists_every_symbol(self):
        text = slots.paytable_embed(2).description
        for name, mult in zip(slots.SYMBOLS, SLOTS_MULTS):
            self.assertIn(f"{name} x3: {mult}x", text)

    def test_render_returns_gif(self):
        self.assertEqual(slots.render_spin(1, 2, 3).read(6)[:3], b"GIF")


if __name__ == "__main__":
    unittest.main()
