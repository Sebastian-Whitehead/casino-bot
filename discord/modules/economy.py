import random
import sqlite3
from functools import wraps
from typing import Tuple, List
from modules.helpers import CASINO_USER_ID


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
        self._ensure_casino_entry()
        self._initialized = True

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
        self.conn = sqlite3.connect(db_path)
        self.cur = self.conn.cursor()
        self.cur.execute("""CREATE TABLE IF NOT EXISTS economy (
            user_id INTEGER NOT NULL PRIMARY KEY,
            money INTEGER NOT NULL DEFAULT 0,
            credits INTEGER NOT NULL DEFAULT 0
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
