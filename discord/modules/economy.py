import random
import sqlite3
import time
from functools import wraps
from typing import Tuple, List
from modules.bank import LocalBank
from modules.helpers import CASINO_USER_ID, CHIP_VALUE, InsufficientFundsException


Entry = Tuple[int, int, int]

CASINO_START_BALANCE = 100000


class Economy:
    def get_all_entries(self) -> List[Entry]:
        """Return all entries in the economy table as a list of (user_id, money, credits)."""
        self.cur.execute("SELECT * FROM economy")
        return self.cur.fetchall()
    """A wrapper for the economy database (Singleton)"""
    _instance = None
    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, '_instance') or cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def _commit(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            result = func(self, *args, **kwargs)
            self.conn.commit()
            return result
        return wrapper

    def __init__(self):
        if getattr(self, '_initialized', False):
            return
        self.casino_user_id = CASINO_USER_ID
        self.open()
        self.bank = LocalBank(self)
        self._migrate_cash_wipe()
        self._ensure_casino_entry()
        self._initialized = True

    def _migrate_cash_wipe(self):
        """One-time (PRAGMA user_version 0 -> 1): back up the db, zero all money, reset casino money."""
        if self.cur.execute("PRAGMA user_version").fetchone()[0] >= 1:
            return
        if self.cur.execute("SELECT COUNT(*) FROM economy").fetchone()[0]:
            if self.db_path != ':memory:':
                dest = sqlite3.connect(self.db_path + '.pre-chips.bak')
                with dest:
                    self.conn.backup(dest)
                dest.close()
            self.cur.execute("UPDATE economy SET money=0")
            self.cur.execute("INSERT OR IGNORE INTO economy(user_id, money, credits) VALUES(?,0,0)",
                             (self.casino_user_id,))
            self.cur.execute("UPDATE economy SET money=? WHERE user_id=?",
                             (CASINO_START_BALANCE, self.casino_user_id))
        self.cur.execute("PRAGMA user_version=1")
        self.conn.commit()

    @staticmethod
    def _check(amount):
        if type(amount) is not int or amount <= 0:
            raise ValueError(f"amount must be a positive int, got {amount!r}")

    def get_chips(self, user_id: int) -> int:
        return self.get_entry(user_id)[2]

    def _adjust_chips(self, pairs, statements=()):
        """Apply [(uid, delta)] plus extra [(sql, params)] in one transaction."""
        try:
            for uid, delta in pairs:
                self.cur.execute("UPDATE economy SET credits=credits+? WHERE user_id=?", (delta, uid))
            for sql, params in statements:
                self.cur.execute(sql, params)
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise

    def buy_chips(self, user_id: int, n: int) -> bool:
        if type(n) is not int or n <= 0:
            return False
        price = n * CHIP_VALUE
        if not self.bank.withdraw(user_id, price):
            return False
        try:
            self._adjust_chips([(user_id, n)])
        except Exception:
            self.bank.deposit(user_id, price)
            raise
        return True

    def cash_out(self, user_id: int, n: int) -> None:
        self._check(n)
        have = self.get_chips(user_id)
        if have < n:
            raise InsufficientFundsException(have, n)
        value = n * CHIP_VALUE
        # casino bank cannot pay: reported as a shortfall of the bank money, chips untouched
        if not self.bank.deposit(user_id, value):
            raise InsufficientFundsException(self.bank.balance(self.casino_user_id), value)
        try:
            self._adjust_chips([(user_id, -n)])
        except Exception:
            self.bank.withdraw(user_id, value)
            raise

    def place_bet(self, user_id: int, n: int) -> None:
        self._check(n)
        have = self.get_chips(user_id)
        if have < n:
            raise InsufficientFundsException(have, n)
        self._adjust_chips([(user_id, -n), (self.casino_user_id, n)])

    def pay_out(self, user_id: int, n: int) -> None:
        self._check(n)
        self.get_entry(user_id)
        self._adjust_chips([(self.casino_user_id, -n), (user_id, n)])

    # --- wagers: every bet is held under a game id until it is settled or refunded ---

    def open_wager(self, game_id: str, user_id: int, game: str, amount: int) -> None:
        """Withdraw the stake from the player's chips into the casino, recorded under game_id.
        Raises InsufficientFundsException; a second open for the same (game_id, user) raises IntegrityError."""
        self._check(amount)
        have = self.get_chips(user_id)
        if have < amount:
            raise InsufficientFundsException(have, amount)
        self._adjust_chips(
            [(user_id, -amount), (self.casino_user_id, amount)],
            [("INSERT INTO wagers(game_id, user_id, game, amount, created_at) VALUES(?,?,?,?,?)",
              (game_id, user_id, game, amount, time.time()))])

    def _close_wager(self, game_id, user_id, status, payout_for):
        """Close an open wager once; returns False if it was already closed (idempotent)."""
        row = self.cur.execute("SELECT amount, status FROM wagers WHERE game_id=? AND user_id=?",
                               (game_id, user_id)).fetchone()
        if row is None:
            raise KeyError(f"no wager {game_id!r} for user {user_id}")
        amount, current = row
        if current != 'open':
            return False
        payout = payout_for(amount)
        pairs = [(self.casino_user_id, -payout), (user_id, payout)] if payout > 0 else []
        self.get_entry(user_id)
        self._adjust_chips(pairs, [(
            "UPDATE wagers SET status=?, payout=?, closed_at=? WHERE game_id=? AND user_id=? AND status='open'",
            (status, payout, time.time(), game_id, user_id))])
        return True

    def settle_wager(self, game_id: str, user_id: int, payout: int) -> bool:
        """Pay `payout` chips (total returned, 0 on a loss) and close the wager. False if already closed."""
        if type(payout) is not int or payout < 0:
            raise ValueError(f"payout must be a non-negative int, got {payout!r}")
        return self._close_wager(game_id, user_id, 'settled', lambda amount: payout)

    def refund_wager(self, game_id: str, user_id: int) -> bool:
        """Return the stake and close the wager. False if already closed."""
        return self._close_wager(game_id, user_id, 'refunded', lambda amount: amount)

    def refund_open_wagers(self) -> int:
        """Refund every still-open wager (their games died with the previous process). Returns the count."""
        rows = self.cur.execute("SELECT game_id, user_id FROM wagers WHERE status='open'").fetchall()
        return sum(self.refund_wager(g, u) for g, u in rows)

    def _ensure_casino_entry(self):
        self.cur.execute(
            "SELECT user_id FROM economy WHERE user_id=?",
            (self.casino_user_id,)
        )
        if self.cur.fetchone() is None:
            self.cur.execute(
                "INSERT INTO economy(user_id, money, credits) VALUES(?,?,?)",
                (self.casino_user_id, CASINO_START_BALANCE, 0)
            )
            self.conn.commit()

    @_commit
    def bind_casino_user(self, user_id: int) -> Entry:
        """Bind casino funds to the authenticated bot user."""
        if user_id == self.casino_user_id:
            return self.get_entry(user_id)

        old_user_id = self.casino_user_id
        self.cur.execute(
            "SELECT * FROM economy WHERE user_id=?",
            (user_id,)
        )
        bot_entry = self.cur.fetchone()
        if bot_entry is None:
            self.cur.execute(
                "UPDATE economy SET user_id=? WHERE user_id=?",
                (user_id, old_user_id)
            )
        else:
            self.cur.execute(
                "DELETE FROM economy WHERE user_id=?",
                (old_user_id,)
            )
        self.casino_user_id = user_id
        self._ensure_casino_entry()
        return self.get_entry(user_id)

    def open(self):
        """Initializes the database"""
        import os
        db_path = os.environ.get('ECONOMY_DB_PATH') or os.path.join(os.path.dirname(os.path.dirname(__file__)), 'economy.db')
        self.db_path = db_path
        self.conn = sqlite3.connect(db_path)
        self.cur = self.conn.cursor()
        self.cur.execute("""CREATE TABLE IF NOT EXISTS economy (
            user_id INTEGER NOT NULL PRIMARY KEY,
            money INTEGER NOT NULL DEFAULT 0,
            credits INTEGER NOT NULL DEFAULT 0
        )""")
        # one row per (game, player) stake; status moves open -> settled | refunded exactly once
        self.cur.execute("""CREATE TABLE IF NOT EXISTS wagers (
            game_id TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            game TEXT NOT NULL,
            amount INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            payout INTEGER,
            created_at REAL NOT NULL,
            closed_at REAL,
            PRIMARY KEY (game_id, user_id)
        )""")

    def close(self):
        """Safely closes the database"""
        if self.conn:
            self.conn.commit()
            self.cur.close()
            self.conn.close()

    def get_entry(self, user_id: int) -> Entry:
        self.cur.execute(
            "SELECT * FROM economy WHERE user_id=:user_id",
            {'user_id': user_id}
        )
        result = self.cur.fetchone()
        if result: return result
        return self.new_entry(user_id)

    @_commit
    def new_entry(self, user_id: int) -> Entry:
        try:
            self.cur.execute(
                "INSERT INTO economy(user_id, money, credits) VALUES(?,?,?)",
                (user_id, 0, 0)
            )
            return self.get_entry(user_id)
        except sqlite3.IntegrityError:
            return self.get_entry(user_id)

    @_commit
    def remove_entry(self, user_id: int) -> None:
        self.cur.execute(
            "DELETE FROM economy WHERE user_id=:user_id",
            {'user_id': user_id}
        )

    @_commit
    def set_money(self, user_id: int, money: int) -> Entry:
        self.cur.execute(
            "UPDATE economy SET money=? WHERE user_id=?",
            (money, user_id)
        )
        return self.get_entry(user_id)

    @_commit
    def set_credits(self, user_id: int, credits: int) -> Entry:
        self.cur.execute(
            "UPDATE economy SET credits=? WHERE user_id=?",
            (credits, user_id)
        )
        return self.get_entry(user_id)

    @_commit
    def add_money(self, user_id: int, money_to_add: int) -> Entry:
        # If not casino, transfer to/from casino
        if user_id != self.casino_user_id:
            # Player loses money, casino gains it
            self.add_money(self.casino_user_id, -money_to_add)
        money = self.get_entry(user_id)[1]
        total = money + money_to_add
        if total < 0:
            total = 0
        self.set_money(user_id, total)
        return self.get_entry(user_id)

    @_commit
    def add_credits(self, user_id: int, credits_to_add: int) -> Entry:
        credits = self.get_entry(user_id)[2]
        total = credits + credits_to_add
        if total < 0:
            total = 0
        self.set_credits(user_id, total)
        return self.get_entry(user_id)

    def random_entry(self) -> Entry:
        self.cur.execute("SELECT * FROM economy")
        return random.choice(self.cur.fetchall())

    def top_entries(self, n: int=0) -> List[Entry]:
        self.cur.execute("SELECT * FROM economy ORDER BY money DESC")
        return (self.cur.fetchmany(n) if n else self.cur.fetchall())
