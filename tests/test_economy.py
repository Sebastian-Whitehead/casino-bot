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
from modules.economy import Economy  # noqa: E402
from modules.bank import CASINO_START_BANK  # noqa: E402
from modules.helpers import InsufficientFundsException, CHIP_VALUE, payout  # noqa: E402
os.chdir(_CWD)  # helpers chdirs to discord/, which breaks unittest discovery

U = 111


def fresh(path, seed=None):
    """New Economy on `path`, optionally pre-seeded with raw rows [(uid, money, credits)] (user_version 0, the old three-column schema)."""
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
        self.e.bank.balance(self.cid)  # seeds the casino bank account

    def tearDown(self):
        self.e.close()
        Economy._instance = None

    def total_money(self):
        return self.e.cur.execute("SELECT SUM(balance) FROM bank_accounts").fetchone()[0]

    def total_chips(self):
        return sum(r[1] for r in self.e.get_all_entries())

    def test_fresh_db_has_two_column_schema(self):
        self.assertEqual(self.e.cur.execute("PRAGMA user_version").fetchone()[0], 3)
        self.assertFalse(os.path.exists(self.path + '.pre-restructure.bak'))
        cols = [r[1] for r in self.e.cur.execute("PRAGMA table_info(economy)")]
        self.assertEqual(cols, ['user_id', 'chips'])
        self.assertEqual(self.e.get_entry(self.cid), (self.cid, 0))
        self.assertEqual(self.e.bank.balance(self.cid), CASINO_START_BANK)

    def test_buy_cash_out_round_trip(self):
        self.e.bank.set_balance(U, 100 * CHIP_VALUE)
        total = self.total_money()
        self.assertTrue(self.e.buy_chips(U, 30))
        self.assertEqual(self.e.get_chips(U), 30)
        self.assertEqual(self.e.bank.balance(U), 70 * CHIP_VALUE)
        self.e.cash_out(U, 30)
        self.assertEqual(self.e.get_chips(U), 0)
        self.assertEqual(self.e.bank.balance(U), 100 * CHIP_VALUE)
        self.assertEqual(self.total_money(), total)
        self.assertEqual(self.e.bank.balance(self.cid), CASINO_START_BANK)

    def test_insufficient_funds(self):
        self.e.bank.set_balance(U, 5 * CHIP_VALUE)
        self.assertFalse(self.e.buy_chips(U, 6))
        self.assertEqual((self.e.bank.balance(U), self.e.get_chips(U)), (5 * CHIP_VALUE, 0))
        with self.assertRaises(InsufficientFundsException):
            self.e.cash_out(U, 1)
        self.assertEqual((self.e.bank.balance(U), self.e.get_chips(U)), (5 * CHIP_VALUE, 0))

    def test_zero_negative_and_non_int_rejected(self):
        self.e.bank.set_balance(U, 1000)
        self.e.set_chips(U, 10)
        for bad in (0, -3, 1.5, True, "2"):
            self.assertFalse(self.e.buy_chips(U, bad))
            for fn in (self.e.cash_out,):
                with self.assertRaises(ValueError):
                    fn(U, bad)
        self.assertEqual((self.e.bank.balance(U), self.e.get_chips(U)), (1000, 10))

    def test_bank_withdraw_deposit_false_cases(self):
        b = self.e.bank
        self.e.bank.set_balance(U, 50)
        for amt in (0, -1, 51, 1.5):
            self.assertFalse(b.withdraw(U, amt))
            self.assertFalse(b.deposit(U, amt) if amt != 51 else False)
        self.assertEqual(b.balance(U), 50)
        self.assertTrue(b.withdraw(U, 50))
        self.assertEqual(b.balance(U), 0)
        self.assertFalse(b.withdraw(U, 1))
        # casino cannot pay more than it has
        self.assertFalse(b.deposit(U, CASINO_START_BANK + 100))
        self.assertEqual(b.balance(U), 0)

    def test_failed_chip_credit_refunds_bank(self):
        self.e.bank.set_balance(U, 100)
        self.e._adjust_chips = lambda pairs, statements=(): (_ for _ in ()).throw(RuntimeError("boom"))
        with self.assertRaises(RuntimeError):
            self.e.buy_chips(U, 3)
        self.assertEqual(self.e.bank.balance(U), 100)

    def test_bet_and_payout_conserve_chips(self):
        self.e.bank.set_balance(U, 100)
        self.e.buy_chips(U, 10)
        total = self.total_chips()
        self.e.open_wager("g", U, "Slots", 4)
        self.assertEqual(self.e.get_chips(U), 6)
        self.assertEqual(self.e.get_chips(self.cid), 4)
        self.e.settle_game("g", {U: payout(4, 3.5)})
        self.assertEqual(self.e.get_chips(U), 20)
        self.assertEqual(self.total_chips(), total)

    def test_wager_open_settle_is_idempotent(self):
        self.e.set_chips(U, 10)
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
        self.e.set_chips(U, 10)
        self.e.open_wager("g2", U, "Blackjack", 3)
        self.assertTrue(self.e.settle_wager("g2", U, 0))
        self.assertEqual(self.e.get_chips(U), 7)
        self.e.open_wager("g3", U, "Blackjack", 3)
        self.assertTrue(self.e.refund_wager("g3", U))
        self.assertEqual(self.e.get_chips(U), 7)

    def test_wager_rejects_insufficient_duplicate_and_unknown(self):
        self.e.set_chips(U, 3)
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
        self.e.set_chips(U, 5)
        self.e.get_entry(222)
        self.e.set_chips(222, 5)
        self.e.open_wager("duel", U, "Coin Flip", 5)
        self.e.open_wager("duel", 222, "Coin Flip", 5)
        self.assertTrue(self.e.settle_wager("duel", U, 9))  # pot 10 minus a 1 chip fee
        self.assertTrue(self.e.settle_wager("duel", 222, 0))
        self.assertEqual((self.e.get_chips(U), self.e.get_chips(222)), (9, 0))

    def test_open_wagers_are_refunded_on_startup(self):
        self.e.set_chips(U, 10)
        self.e.open_wager("orphan", U, "Blackjack", 6)
        self.assertEqual(self.e.refund_open_wagers(), 1)
        self.assertEqual(self.e.get_chips(U), 10)
        self.assertEqual(self.e.refund_open_wagers(), 0)

    def log(self, game_id):
        cols = "user_id, chips_wagered, chips_paid_out, result, winner, game"
        return self.e.cur.execute(
            f"SELECT {cols} FROM game_log WHERE game_id=? ORDER BY user_id", (game_id,)).fetchall()

    def test_game_log_solo_win_loss_push(self):
        self.e.set_chips(U, 30)
        for gid, payout in (("w", 8), ("l", 0), ("p", 4)):
            self.e.open_wager(gid, U, "Slots", 4)
            self.assertTrue(self.e.settle_game(gid, {U: payout}))
        self.assertEqual(self.log("w"), [(U, 4, 8, "win", str(U), "Slots")])
        self.assertEqual(self.log("l"), [(U, 4, 0, "loss", "house", "Slots")])  # a loss: the house wins
        self.assertEqual(self.log("p"), [(U, 4, 4, "push", "none", "Slots")])
        self.assertEqual(self.e.get_chips(U), 30 - 4 + 4)  # +4 net on the win, -4 on the loss, 0 on the push

    def test_game_log_challenge_records_both_players(self):
        self.e.get_entry(222)
        self.e.set_chips(U, 5)
        self.e.set_chips(222, 5)
        self.e.open_wager("duel", U, "Coin Flip", 5)
        self.e.open_wager("duel", 222, "Coin Flip", 5)
        self.assertTrue(self.e.settle_game("duel", {222: 9, U: 0}))
        self.assertEqual(self.log("duel"), [(U, 5, 0, "loss", "222", "Coin Flip"),
                                            (222, 5, 9, "win", "222", "Coin Flip")])
        self.assertEqual((self.e.get_chips(U), self.e.get_chips(222)), (0, 9))

    def test_leaderboards_view_ranks_by_net(self):
        self.e.get_entry(222)
        self.e.set_chips(U, 5)
        self.e.set_chips(222, 5)
        self.e.open_wager("duel", U, "Coin Flip", 5)
        self.e.open_wager("duel", 222, "Coin Flip", 5)
        self.e.settle_game("duel", {222: 9, U: 0})
        rows = self.e.cur.execute(
            "SELECT user_id, games, winnings, losses, net, rank FROM leaderboards ORDER BY rank").fetchall()
        self.assertEqual(rows, [(222, 1, 4, 0, 4, 1), (U, 1, 0, 5, -5, 2)])

    def test_game_leaderboard_is_per_game(self):
        self.e.set_chips(U, 20)
        for gid, game, pay in (("a", "Slots", 10), ("b", "Dice Roll", 0)):
            self.e.open_wager(gid, U, game, 5)
            self.e.settle_game(gid, {U: pay})
        self.assertEqual(self.e.leaderboard(10, "Slots"), [(1, U, 5, 0, 5)])
        self.assertEqual(self.e.leaderboard(10, "Dice Roll"), [(1, U, 0, 5, -5)])
        self.assertEqual(self.e.leaderboard(10), [(1, U, 5, 5, 0)])

    def test_test_mode_games_are_not_logged(self):
        from modules import helpers
        from unittest import mock
        self.e.set_chips(U, 10)
        with mock.patch.object(helpers, "TEST_MODE", True):
            self.e.open_wager("t", U, "Slots", 5)
            self.e.settle_game("t", {U: 10})
        self.assertEqual(self.log("t"), [])
        self.assertEqual(self.e.get_chips(U), 15)  # still paid out

    def test_game_log_tie_and_no_double_write(self):
        self.e.get_entry(222)
        self.e.set_chips(U, 5)
        self.e.set_chips(222, 5)
        self.e.open_wager("tie", U, "Dice Roll", 5)
        self.e.open_wager("tie", 222, "Dice Roll", 5)
        self.assertTrue(self.e.settle_game("tie", {U: 5, 222: 5}))
        self.assertEqual({r[3] for r in self.log("tie")}, {"push"})
        self.assertEqual({r[4] for r in self.log("tie")}, {"none"})
        self.assertFalse(self.e.settle_game("tie", {U: 5, 222: 5}))  # retry: nothing paid, nothing logged
        self.assertEqual(len(self.log("tie")), 2)
        self.assertEqual((self.e.get_chips(U), self.e.get_chips(222)), (5, 5))

    def test_game_log_not_written_for_refunds_or_failed_settle(self):
        self.e.set_chips(U, 10)
        self.e.open_wager("r", U, "Blackjack", 3)
        self.e.refund_wager("r", U)
        self.assertEqual(self.log("r"), [])
        self.e.open_wager("x", U, "Blackjack", 3)
        with self.assertRaises(KeyError):  # second player has no wager: nothing may change
            self.e.settle_game("x", {U: 6, 999: 0})
        self.assertEqual(self.log("x"), [])
        self.assertEqual(self.e.get_chips(U), 7)

    def test_version_2_database_renames_credits_to_chips(self):
        path = os.path.join(tempfile.mkdtemp(dir=_TMP), 'v2.db')
        e = fresh(path)
        e.set_chips(U, 12)
        e.close()
        c = sqlite3.connect(path)  # put it back into the v2 shape
        c.execute("ALTER TABLE economy RENAME COLUMN chips TO credits")
        c.execute("PRAGMA user_version=2")
        c.commit()
        c.close()
        Economy._instance = None
        e = Economy()
        self.assertEqual([r[1] for r in e.cur.execute("PRAGMA table_info(economy)")], ['user_id', 'chips'])
        self.assertEqual(e.get_chips(U), 12)  # data kept
        self.assertEqual(e.cur.execute("PRAGMA user_version").fetchone()[0], 3)
        self.e = e

    def test_new_user_without_a_row_keeps_bought_chips(self):
        # regression: buy_chips used to charge the bank but credit nothing when the economy row was missing
        newbie = 987654
        self.e.bank.set_balance(newbie, 100 * CHIP_VALUE)
        self.assertTrue(self.e.buy_chips(newbie, 5))
        self.assertEqual(self.e.get_chips(newbie), 5)
        self.assertEqual(self.e.bank.balance(newbie), 95 * CHIP_VALUE)

    def test_test_mode_gives_infinite_bank_money(self):
        from modules import helpers
        from unittest import mock
        broke = 424242  # no bank money at all
        casino_before = self.e.bank.balance(self.cid)
        with mock.patch.object(helpers, "TEST_MODE", True):
            self.assertTrue(self.e.buy_chips(broke, 50))
            self.assertTrue(self.e.buy_chips(broke, 5_000_000))  # far beyond the displayed balance
            self.assertEqual(self.e.get_chips(broke), 5_000_050)
            self.e.cash_out(broke, 100)
            self.assertFalse(self.e.buy_chips(broke, 0))  # invalid amounts are still rejected
            self.assertFalse(self.e.buy_chips(broke, -5))
        self.assertEqual(self.e.bank.balance(broke), 0)  # real balances untouched
        self.assertEqual(self.e.bank.balance(self.cid), casino_before)
        self.assertFalse(self.e.buy_chips(broke, 1))  # test mode off again: no money, no chips
        self.assertEqual(self.e.get_chips(broke), 5_000_050 - 100)

    def test_restructure_wipes_old_data_once(self):
        path = os.path.join(tempfile.mkdtemp(dir=_TMP), 'old.db')
        cid = Economy().casino_user_id  # same config id the new instance will use
        e = fresh(path, seed=[(cid, 5, 0), (U, 999, 7), (222, 50, 3)])
        self.assertTrue(os.path.exists(path + '.pre-restructure.bak'))
        old = sqlite3.connect(path + '.pre-restructure.bak')
        self.assertEqual(old.execute("SELECT COUNT(*) FROM economy").fetchone()[0], 3)  # backup keeps old data
        old.close()
        self.assertEqual([r[1] for r in e.cur.execute("PRAGMA table_info(economy)")], ['user_id', 'chips'])
        self.assertEqual(e.get_all_entries(), [(cid, 0)])  # everything wiped, only the casino row remains
        self.assertEqual(e.get_entry(U), (U, 0))
        self.assertEqual(e.bank.balance(cid), CASINO_START_BANK)
        # second start: must not wipe again
        e.set_chips(U, 42)
        e.close()
        Economy._instance = None
        e = Economy()
        self.assertEqual(e.get_chips(U), 42)
        self.assertEqual(e.cur.execute("PRAGMA user_version").fetchone()[0], 3)
        self.e = e

    def test_set_chips_creates_the_row(self):
        self.e.set_chips(555, 9)
        self.assertEqual(self.e.get_chips(555), 9)

    def test_casino_rebind_moves_bank_and_chips(self):
        old = self.e.casino_user_id
        self.e.bank.set_balance(old, 777)
        self.e.set_chips(old, 5)
        self.e.bind_casino_user(old + 1)
        self.assertEqual(self.e.bank.balance(old + 1), 777)
        self.assertEqual(self.e.get_chips(old + 1), 5)


if __name__ == '__main__':
    unittest.main()


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.eco = fresh(os.path.join(tempfile.mkdtemp(), 'r.db'))
        self.eco.set_chips(U, 7)
        self.eco.set_chips(222, 3)

    def test_local_bank_has_no_ledger(self):
        self.assertIsNone(self.eco.reconcile())

    def test_balanced_and_drift(self):
        from types import SimpleNamespace
        backed = 10 * CHIP_VALUE * 100
        self.eco.bank = SimpleNamespace(net_chip_money=lambda: backed)
        self.assertEqual(self.eco.reconcile(), (10, backed, backed, 0))
        self.eco.bank = SimpleNamespace(net_chip_money=lambda: backed - 500)
        self.assertEqual(self.eco.reconcile()[3], -500)


class ForceCashOutTests(unittest.TestCase):
    def setUp(self):
        self.eco = fresh(os.path.join(tempfile.mkdtemp(), 'c.db'))
        self.eco.bank.set_balance(self.eco.casino_user_id, 100000)
        self.eco.set_chips(U, 4)
        self.eco.set_chips(222, 6)

    def test_sells_all_chips_of_one_player_only(self):
        self.assertEqual(self.eco.force_cash_out(U), 4)
        self.assertEqual((self.eco.get_chips(U), self.eco.get_chips(222)), (0, 6))
        self.assertEqual(self.eco.bank.balance(U), 4 * CHIP_VALUE)

    def test_open_wager_is_refunded_then_sold(self):
        self.eco.open_wager('g1', U, 'coinflip', 3)  # 3 of the 4 chips are held by a game
        self.assertEqual(self.eco.force_cash_out(U), 4)
        self.assertEqual(self.eco.bank.balance(U), 4 * CHIP_VALUE)

    def test_casino_cannot_pay_changes_nothing(self):
        self.eco.bank.set_balance(self.eco.casino_user_id, 0)
        with self.assertRaises(InsufficientFundsException):
            self.eco.force_cash_out(U)
        self.assertEqual(self.eco.get_chips(U), 4)

    def test_refuses_the_casino(self):
        with self.assertRaises(ValueError):
            self.eco.force_cash_out(self.eco.casino_user_id)


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.eco = fresh(os.path.join(tempfile.mkdtemp(), 'b.db'))
        self.eco.set_chips(U, 9)

    def test_snapshot_is_a_valid_copy(self):
        path = os.path.join(tempfile.mkdtemp(), 'copy.db')
        with open(path, 'wb') as f:
            f.write(self.eco.snapshot())
        c = sqlite3.connect(path)
        self.assertEqual(c.execute("SELECT chips FROM economy WHERE user_id=?", (U,)).fetchone()[0], 9)
        c.close()

    def test_backup_uploads_snapshot_when_supabase(self):
        from types import SimpleNamespace
        got = {}
        self.eco.bank = SimpleNamespace(save_backup=lambda data, label, keep, age: got.update(n=len(data), keep=keep, age=age) or {'id': 1})
        self.assertEqual(self.eco.backup_to_supabase(3, 48), {'id': 1})
        self.assertGreater(got['n'], 0)
        self.assertEqual((got['keep'], got['age']), (3, 48))

    def test_local_bank_skips_backup(self):
        self.assertIsNone(self.eco.backup_to_supabase(3, 48))
