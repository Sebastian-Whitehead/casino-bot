import random
import sqlite3
import time
from functools import wraps
from typing import Tuple, List
from modules import helpers
from modules.bank import LocalBank
from modules.helpers import CASINO_USER_ID, CHIP_VALUE, InsufficientFundsException


Entry = Tuple[int, int]  # (user_id, chips)


class Economy:
    """A wrapper for the economy database (Singleton)"""
    _instance = None
    def __new__(cls, *args, **kwargs):
        if not hasattr(cls, '_instance') or cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def get_all_entries(self) -> List[Entry]:
        """Return all entries in the economy table as a list of (user_id, chips)."""
        self.cur.execute("SELECT * FROM economy")
        return self.cur.fetchall()

    def leaderboard(self, n: int = 10, game: str = None):
        """Top n rows (rank, user_id, winnings, losses, net); overall, or for one game name."""
        if game is None:
            return self.cur.execute("SELECT rank, user_id, winnings, losses, net FROM leaderboards "
                                    "ORDER BY rank, user_id LIMIT ?", (n,)).fetchall()
        return self.cur.execute("SELECT rank, user_id, winnings, losses, net FROM game_leaderboards WHERE game=? "
                                "ORDER BY rank, user_id LIMIT ?", (game, n)).fetchall()

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
        self._migrate_restructure()
        self._ensure_casino_entry()
        self._initialized = True

    def _migrate_restructure(self):
        """One-time (PRAGMA user_version < 2; version 2 only renames credits to chips): the economy table becomes just (user_id, chips).
        Everything in the old table is wiped (a backup copy of the file is kept) and open wagers are dropped,
        since the stakes they refer to are gone."""
        version = self.cur.execute("PRAGMA user_version").fetchone()[0]
        if version == 2:  # already restructured, the column was still called credits
            self.cur.execute("ALTER TABLE economy RENAME COLUMN credits TO chips")
            self.cur.execute("PRAGMA user_version=3")
            self.conn.commit()
            return
        if version >= 3:
            return
        had_data = self.cur.execute("SELECT COUNT(*) FROM economy").fetchone()[0]
        if had_data and self.db_path != ':memory:':
            dest = sqlite3.connect(self.db_path + '.pre-restructure.bak')
            with dest:
                self.conn.backup(dest)
            dest.close()
        self.cur.execute("DROP TABLE economy")
        self.cur.execute(self._ECONOMY_SCHEMA)
        self.cur.execute("DELETE FROM wagers WHERE status='open'")
        self.cur.execute("PRAGMA user_version=3")
        self.conn.commit()

    _ECONOMY_SCHEMA = """CREATE TABLE economy (
            user_id INTEGER NOT NULL PRIMARY KEY,
            chips INTEGER NOT NULL DEFAULT 0
        )"""

    @staticmethod
    def _check(amount):
        if type(amount) is not int or amount <= 0:
            raise ValueError(f"amount must be a positive int, got {amount!r}")

    def get_chips(self, user_id: int) -> int:
        return self.get_entry(user_id)[1]

    def _adjust_chips(self, pairs, statements=()):
        """Apply [(uid, delta)] plus extra [(sql, params)] in one transaction."""
        try:
            for uid, delta in pairs:
                # a plain UPDATE would silently drop chips for a user with no row yet
                self.cur.execute("INSERT OR IGNORE INTO economy(user_id, chips) VALUES(?,0)", (uid,))
                self.cur.execute("UPDATE economy SET chips=chips+? WHERE user_id=?", (delta, uid))
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

    def settle_game(self, game_id: str, payouts: dict) -> bool:
        """Resolve a whole game in one transaction: pay each player's chips ({user_id: total chips returned,
        0 on a loss}), close their wagers and write the game_log rows.
        result (per player): win if paid more than wagered, push if equal, loss if less.
        winner (same on every row): the winning user id; 'house' if every player lost; 'none' on a push.
        Returns False, changing nothing, if any wager is already closed (so a retry never pays twice)."""
        rows = {}
        for uid, payout in payouts.items():
            if type(payout) is not int or payout < 0:
                raise ValueError(f"payout must be a non-negative int, got {payout!r}")
            row = self.cur.execute("SELECT amount, status, game FROM wagers WHERE game_id=? AND user_id=?",
                                   (game_id, uid)).fetchone()
            if row is None:
                raise KeyError(f"no wager {game_id!r} for user {uid}")
            if row[1] != 'open':
                return False
            rows[uid] = row
        results = {uid: ('win' if payouts[uid] > amount else 'push' if payouts[uid] == amount else 'loss')
                   for uid, (amount, _, _) in rows.items()}
        winners = [uid for uid, r in results.items() if r == 'win']
        winner = str(winners[0]) if winners else ('house' if all(r == 'loss' for r in results.values()) else 'none')
        now = time.time()
        pairs, statements = [], []
        for uid, (amount, _, game) in rows.items():
            self.get_entry(uid)
            if payouts[uid] > 0:
                pairs += [(self.casino_user_id, -payouts[uid]), (uid, payouts[uid])]
            statements.append(("UPDATE wagers SET status='settled', payout=?, closed_at=? "
                               "WHERE game_id=? AND user_id=? AND status='open'", (payouts[uid], now, game_id, uid)))
            if not helpers.TEST_MODE:  # test games use fake bank money: not logged, so not on the leaderboards
                statements.append(("INSERT INTO game_log(game_id, game, user_id, chips_wagered, chips_paid_out, "
                                   "result, winner, resolved_at) VALUES(?,?,?,?,?,?,?,?)",
                                   (game_id, game, uid, amount, payouts[uid], results[uid], winner, now)))
        self._adjust_chips(pairs, statements)
        return True

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
                "INSERT INTO economy(user_id, chips) VALUES(?,?)",
                (self.casino_user_id, 0)
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
        self.bank.rebind_casino(old_user_id, user_id)
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
        self.cur.execute(self._ECONOMY_SCHEMA.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1))
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
        # one row per participant per resolved game; `winner` is the same on every row of a game
        self.cur.execute("""CREATE TABLE IF NOT EXISTS game_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            game TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            chips_wagered INTEGER NOT NULL,
            chips_paid_out INTEGER NOT NULL,
            result TEXT NOT NULL,
            winner TEXT NOT NULL,
            resolved_at REAL NOT NULL,
            UNIQUE (game_id, user_id)
        )""")
        self.cur.execute("CREATE TABLE IF NOT EXISTS bonus_claims (user_id INTEGER PRIMARY KEY, ts REAL NOT NULL)")
        # derived from game_log, so it can never drift; recreated each start so edits here apply
        self.cur.execute("DROP VIEW IF EXISTS game_leaderboards")
        self.cur.execute("""CREATE VIEW game_leaderboards AS
            SELECT game, user_id, games, winnings, losses, winnings - losses AS net,
                   RANK() OVER (PARTITION BY game ORDER BY winnings - losses DESC) AS rank
            FROM (SELECT game, user_id, COUNT(*) AS games,
                         SUM(MAX(chips_paid_out - chips_wagered, 0)) AS winnings,
                         SUM(MAX(chips_wagered - chips_paid_out, 0)) AS losses
                  FROM game_log GROUP BY game, user_id)""")
        self.cur.execute("DROP VIEW IF EXISTS leaderboards")
        self.cur.execute("""CREATE VIEW leaderboards AS
            SELECT user_id, games, winnings, losses, winnings - losses AS net,
                   RANK() OVER (ORDER BY winnings - losses DESC) AS rank
            FROM (SELECT user_id, COUNT(*) AS games,
                         SUM(MAX(chips_paid_out - chips_wagered, 0)) AS winnings,
                         SUM(MAX(chips_wagered - chips_paid_out, 0)) AS losses
                  FROM game_log GROUP BY user_id)""")

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
                "INSERT INTO economy(user_id, chips) VALUES(?,?)",
                (user_id, 0)
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
    def set_chips(self, user_id: int, chips: int) -> Entry:
        self.get_entry(user_id)  # make sure the row exists
        self.cur.execute(
            "UPDATE economy SET chips=? WHERE user_id=?",
            (chips, user_id)
        )
        return self.get_entry(user_id)

    @_commit
    def add_chips(self, user_id: int, chips_to_add: int) -> Entry:
        total = max(0, self.get_entry(user_id)[1] + chips_to_add)
        self.set_chips(user_id, total)
        return self.get_entry(user_id)

    def random_entry(self) -> Entry:
        self.cur.execute("SELECT * FROM economy")
        return random.choice(self.cur.fetchall())

    def top_entries(self, n: int=0) -> List[Entry]:
        self.cur.execute("SELECT * FROM economy ORDER BY chips DESC")
        return (self.cur.fetchmany(n) if n else self.cur.fetchall())
