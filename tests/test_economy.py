import os
import sqlite3
import sys
import tempfile
import unittest

# Must be set before economy is first used; never touch the real economy.db.
_TMP = tempfile.mkdtemp()
os.environ['ECONOMY_DB_PATH'] = os.path.join(_TMP, 'boot.db')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'discord'))

_CWD = os.getcwd()
from modules.economy import Economy, CASINO_START_BALANCE  # noqa: E402
from modules.helpers import InsufficientFundsException, CHIP_VALUE, payout  # noqa: E402
os.chdir(_CWD)  # helpers chdirs to discord/, which breaks unittest discovery

U = 111


def fresh(path, seed=None):
    """New Economy on `path`, optionally pre-seeded with raw rows [(uid, money, credits)] (user_version 0)."""
    os.environ['ECONOMY_DB_PATH'] = path
    if seed:
        c = sqlite3.connect(path)
        c.execute("CREATE TABLE economy (user_id INTEGER NOT NULL PRIMARY KEY, money INTEGER NOT NULL DEFAULT 0, credits INTEGER NOT NULL DEFAULT 0)")
        c.executemany("INSERT INTO economy VALUES(?,?,?)", seed)
        c.commit()
        c.close()
    if Economy._instance is not None:
        Economy._instance.close()
    Economy._instance = None
    return Economy()


class EconomyTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(dir=_TMP), 'e.db')
        self.e = fresh(self.path)
        self.cid = self.e.casino_user_id
        self.e.get_entry(U)

    def tearDown(self):
        self.e.close()
        Economy._instance = None

    def total_money(self):
        return sum(r[1] for r in self.e.get_all_entries())

    def total_chips(self):
        return sum(r[2] for r in self.e.get_all_entries())

    def test_fresh_db_only_sets_marker(self):
        self.assertEqual(self.e.cur.execute("PRAGMA user_version").fetchone()[0], 1)
        self.assertFalse(os.path.exists(self.path + '.pre-chips.bak'))
        self.assertEqual(self.e.get_entry(self.cid)[1], CASINO_START_BALANCE)

    def test_buy_cash_out_round_trip(self):
        self.e.set_money(U, 100 * CHIP_VALUE)
        total = self.total_money()
        self.assertTrue(self.e.buy_chips(U, 30))
        self.assertEqual(self.e.get_chips(U), 30)
        self.assertEqual(self.e.get_entry(U)[1], 70 * CHIP_VALUE)
        self.e.cash_out(U, 30)
        self.assertEqual(self.e.get_chips(U), 0)
        self.assertEqual(self.e.get_entry(U)[1], 100 * CHIP_VALUE)
        self.assertEqual(self.total_money(), total)
        self.assertEqual(self.e.get_entry(self.cid)[1], CASINO_START_BALANCE)

    def test_insufficient_funds(self):
        self.e.set_money(U, 5 * CHIP_VALUE)
        self.assertFalse(self.e.buy_chips(U, 6))
        self.assertEqual(self.e.get_entry(U)[1:], (5 * CHIP_VALUE, 0))
        with self.assertRaises(InsufficientFundsException):
            self.e.cash_out(U, 1)
        with self.assertRaises(InsufficientFundsException):
            self.e.place_bet(U, 1)
        self.assertEqual(self.e.get_entry(U)[1:], (5 * CHIP_VALUE, 0))

    def test_zero_negative_and_non_int_rejected(self):
        self.e.set_money(U, 1000)
        self.e.set_credits(U, 10)
        for bad in (0, -3, 1.5, True, "2"):
            self.assertFalse(self.e.buy_chips(U, bad))
            for fn in (self.e.cash_out, self.e.place_bet, self.e.pay_out):
                with self.assertRaises(ValueError):
                    fn(U, bad)
        self.assertEqual(self.e.get_entry(U)[1:], (1000, 10))

    def test_bank_withdraw_deposit_false_cases(self):
        b = self.e.bank
        self.e.set_money(U, 50)
        for amt in (0, -1, 51, 1.5):
            self.assertFalse(b.withdraw(U, amt))
            self.assertFalse(b.deposit(U, amt) if amt != 51 else False)
        self.assertEqual(b.balance(U), 50)
        self.assertTrue(b.withdraw(U, 50))
        self.assertEqual(b.balance(U), 0)
        self.assertFalse(b.withdraw(U, 1))
        # casino cannot pay more than it has
        self.assertFalse(b.deposit(U, CASINO_START_BALANCE + 100))
        self.assertEqual(b.balance(U), 0)

    def test_failed_chip_credit_refunds_bank(self):
        self.e.set_money(U, 100)
        self.e._adjust_chips = lambda pairs: (_ for _ in ()).throw(RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            self.e.buy_chips(U, 3)
        self.assertEqual(self.e.get_entry(U)[1], 100)

    def test_bet_and_payout_conserve_chips(self):
        self.e.set_money(U, 100)
        self.e.buy_chips(U, 10)
        total = self.total_chips()
        self.e.place_bet(U, 4)
        self.assertEqual(self.e.get_chips(U), 6)
        self.assertEqual(self.e.get_chips(self.cid), 4)
        self.e.pay_out(U, payout(4, 1.5))
        self.assertEqual(self.e.get_chips(U), 12)
        self.assertEqual(self.total_chips(), total)

    def test_wager_open_settle_is_idempotent(self):
        self.e.set_credits(U, 10)
        total = self.total_chips()
        self.e.open_wager("g1", U, "Slots", 4)
        self.assertEqual(self.e.get_chips(U), 6)
        self.assertTrue(self.e.settle_wager("g1", U, 8))
        self.assertEqual(self.e.get_chips(U), 14)
        self.assertFalse(self.e.settle_wager("g1", U, 8))  # a retry must not pay twice
        self.assertFalse(self.e.refund_wager("g1", U))      # closed wagers cannot be refunded
        self.assertEqual(self.e.get_chips(U), 14)
        self.assertEqual(self.total_chips(), total)

    def test_wager_loss_and_refund(self):
        self.e.set_credits(U, 10)
        self.e.open_wager("g2", U, "Blackjack", 3)
        self.assertTrue(self.e.settle_wager("g2", U, 0))
        self.assertEqual(self.e.get_chips(U), 7)
        self.e.open_wager("g3", U, "Blackjack", 3)
        self.assertTrue(self.e.refund_wager("g3", U))
        self.assertEqual(self.e.get_chips(U), 7)

    def test_wager_rejects_insufficient_duplicate_and_unknown(self):
        self.e.set_credits(U, 3)
        with self.assertRaises(InsufficientFundsException):
            self.e.open_wager("g4", U, "Slots", 4)
        self.assertEqual(self.e.get_chips(U), 3)
        self.e.open_wager("g4", U, "Slots", 2)
        with self.assertRaises(sqlite3.IntegrityError):
            self.e.open_wager("g4", U, "Slots", 1)
        self.assertEqual(self.e.get_chips(U), 1)  # the failed duplicate took nothing
        with self.assertRaises(KeyError):
            self.e.settle_wager("nope", U, 1)
        with self.assertRaises(ValueError):
            self.e.settle_wager("g4", U, -1)

    def test_two_player_wager_shares_a_game_id(self):
        self.e.set_credits(U, 5)
        self.e.get_entry(222)
        self.e.set_credits(222, 5)
        self.e.open_wager("duel", U, "Coin Flip", 5)
        self.e.open_wager("duel", 222, "Coin Flip", 5)
        self.assertTrue(self.e.settle_wager("duel", U, 9))  # pot 10 minus a 1 chip fee
        self.assertTrue(self.e.settle_wager("duel", 222, 0))
        self.assertEqual((self.e.get_chips(U), self.e.get_chips(222)), (9, 0))

    def test_open_wagers_are_refunded_on_startup(self):
        self.e.set_credits(U, 10)
        self.e.open_wager("orphan", U, "Blackjack", 6)
        self.assertEqual(self.e.refund_open_wagers(), 1)
        self.assertEqual(self.e.get_chips(U), 10)
        self.assertEqual(self.e.refund_open_wagers(), 0)

    def test_migration_runs_once_and_keeps_credits(self):
        path = os.path.join(tempfile.mkdtemp(dir=_TMP), 'old.db')
        cid = Economy().casino_user_id  # same config id the new instance will use
        e = fresh(path, seed=[(cid, 5, 0), (U, 999, 7), (222, 50, 3)])
        self.assertTrue(os.path.exists(path + '.pre-chips.bak'))
        self.assertEqual(e.get_entry(U), (U, 0, 7))
        self.assertEqual(e.get_entry(222), (222, 0, 3))
        self.assertEqual(e.get_entry(cid)[1], CASINO_START_BALANCE)
        # second start: must not re-run
        e.set_money(U, 42)
        e.close()
        Economy._instance = None
        e = Economy()
        self.assertEqual(e.get_entry(U)[1], 42)
        self.assertEqual(e.cur.execute("PRAGMA user_version").fetchone()[0], 1)
        self.e = e


if __name__ == '__main__':
    unittest.main()
