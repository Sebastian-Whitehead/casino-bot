import os
import sys
import tempfile
import unittest
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_cwd = os.getcwd()
_tmp = tempfile.mkdtemp()
os.environ["ECONOMY_DB_PATH"] = os.path.join(_tmp, "test.db")
sys.path.insert(0, os.path.join(ROOT, "discord"))

from modules.economy import Economy  # noqa: E402
from modules.helpers import B_COOLDOWN, CHIP_VALUE  # noqa: E402
from cogs import cashier, gambling_helpers  # noqa: E402

os.chdir(_cwd)  # helpers chdirs into discord/ on import

UID = 111


class FakeInteraction:
    def __init__(self, uid=UID):
        self.user = SimpleNamespace(id=uid)
        self.edits = []
        outer = self

        class Resp:
            async def edit_message(self, **kw):
                outer.edits.append(kw)

        self.response = Resp()


class CashierTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.eco = Economy()
        self.eco.bank.set_balance(UID, 0)
        self.eco.set_chips(UID, 0)
        self.eco.cur.execute("DROP TABLE IF EXISTS bonus_claims")
        self.eco.bank.set_balance(self.eco.casino_user_id, 100000)

    async def test_custom_ids_unique(self):
        view = cashier.CashierView(SimpleNamespace(id=UID), self.eco)
        ids = [c.custom_id for c in view.children]
        self.assertEqual(len(ids), len(set(ids)))

    async def test_insufficient_buy_changes_nothing(self):
        self.eco.bank.set_balance(UID, 25)
        view = cashier.CashierView(SimpleNamespace(id=UID), self.eco)
        view.quantity = 3
        i = FakeInteraction()
        await view.confirm.callback(i)
        self.assertEqual((self.eco.bank.balance(UID), self.eco.get_chips(UID)), (25, 0))
        self.assertFalse(view.done)
        self.assertIn("Insufficient funds", i.edits[-1]["embed"].description)

    async def test_buy_success_and_disable(self):
        self.eco.bank.set_balance(UID, 5 * CHIP_VALUE)
        view = cashier.CashierView(SimpleNamespace(id=UID), self.eco)
        view.quantity = 5
        await view.confirm.callback(FakeInteraction())
        self.assertEqual((self.eco.bank.balance(UID), self.eco.get_chips(UID)), (0, 5))
        self.assertTrue(all(c.disabled for c in view.children))

    async def test_cash_out_success_and_insufficient(self):
        self.eco.set_chips(UID, 4)
        view = cashier.CashierView(SimpleNamespace(id=UID), self.eco)
        await view.toggle.callback(FakeInteraction())
        view.quantity = 9
        i = FakeInteraction()
        await view.confirm.callback(i)
        self.assertEqual((self.eco.bank.balance(UID), self.eco.get_chips(UID)), (0, 4))
        self.assertIn("only have 4 chips", i.edits[-1]["embed"].description)
        view.quantity = 4
        await view.confirm.callback(FakeInteraction())
        self.assertEqual((self.eco.bank.balance(UID), self.eco.get_chips(UID)), (4 * CHIP_VALUE, 0))

    async def test_caps_on_mode_switch(self):
        self.eco.bank.set_balance(UID, 7 * CHIP_VALUE)
        self.eco.set_chips(UID, 3)
        view = cashier.CashierView(SimpleNamespace(id=UID), self.eco)
        await view.max_.callback(FakeInteraction())
        self.assertEqual(view.quantity, 7)
        await view.toggle.callback(FakeInteraction())
        self.assertEqual(view.quantity, 3)
        await view.p10.callback(FakeInteraction())
        self.assertEqual(view.quantity, 3)
        await view.m10.callback(FakeInteraction())
        self.assertEqual(view.quantity, 1)

    def test_cashout_all_and_parse(self):
        self.assertEqual(cashier.parse_cashout("ALL", 6), 6)
        self.assertIsNone(cashier.parse_cashout("all", 0))
        self.assertIsNone(cashier.parse_cashout("0", 6))
        self.assertIsNone(cashier.parse_cashout("-2", 6))
        self.assertIsNone(cashier.parse_cashout("x", 6))
        self.eco.set_chips(UID, 6)
        ok, _ = cashier.do_cash_out(self.eco, UID, cashier.parse_cashout("all", 6))
        self.assertTrue(ok)
        self.assertEqual((self.eco.bank.balance(UID), self.eco.get_chips(UID)), (6 * CHIP_VALUE, 0))

    def test_bonus_cooldown(self):
        ok, rem, amount = gambling_helpers.claim_bonus(self.eco, UID, now=1000.0)
        self.assertTrue(ok)
        self.assertEqual(self.eco.bank.balance(UID), amount)
        ok, rem, _ = gambling_helpers.claim_bonus(self.eco, UID, now=1000.0 + 3600)
        self.assertFalse(ok)
        self.assertEqual(rem, int(B_COOLDOWN * 3600 - 3600))
        self.assertEqual(self.eco.bank.balance(UID), amount)
        ok, _, _ = gambling_helpers.claim_bonus(self.eco, UID, now=1000.0 + B_COOLDOWN * 3600)
        self.assertTrue(ok)
        self.assertEqual(self.eco.bank.balance(UID), 2 * amount)


if __name__ == "__main__":
    unittest.main()
