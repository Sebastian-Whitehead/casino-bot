import uuid


class Bank:
    """Bank-money seam. Swap LocalBank for a Supabase implementation later."""

    def balance(self, uid: int) -> int:
        raise NotImplementedError

    def withdraw(self, uid: int, amount: int) -> bool:
        """Take amount from the player. False if amount <= 0 or funds are short; never partial."""
        raise NotImplementedError

    def deposit(self, uid: int, amount: int, kind: str = "sale") -> bool:
        """Give amount to the player (kind: ledger type, 'sale' for a cash-out, 'reward' for a bonus). False if amount <= 0 or the source cannot pay."""
        raise NotImplementedError

    def display(self, uid: int) -> str:
        """Balance for users: test mode has no real balance, so say so."""
        return "unlimited (test mode)" if helpers.TEST_MODE else f"${self.balance(uid):,}"


def _valid(amount) -> bool:
    return type(amount) is int and amount > 0


from modules import helpers

CASINO_START_BANK = 100000
TEST_MODE_BALANCE = 1_000_000  # what balance() reports in test mode; keeps the cashier's Max button sane  # the casino's bank money the first time it is used


class LocalBank(Bank):
    """Placeholder bank in economy.db (table bank_accounts); the casino account is the counterparty.
    Replace with the Supabase bank: it only has to provide balance/withdraw/deposit (+ rebind_casino/set_balance for admin)."""

    def __init__(self, economy):
        self.eco = economy
        economy.cur.execute("CREATE TABLE IF NOT EXISTS bank_accounts ("
                            "user_id INTEGER NOT NULL PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)")
        economy.conn.commit()

    def _ensure(self, uid: int) -> None:
        start = CASINO_START_BANK if uid == self.eco.casino_user_id else 0
        self.eco.cur.execute("INSERT OR IGNORE INTO bank_accounts(user_id, balance) VALUES(?,?)", (uid, start))

    def balance(self, uid: int) -> int:
        if helpers.TEST_MODE:
            return TEST_MODE_BALANCE
        self._ensure(uid)
        self.eco.conn.commit()
        return self.eco.cur.execute("SELECT balance FROM bank_accounts WHERE user_id=?", (uid,)).fetchone()[0]

    def set_balance(self, uid: int, amount: int) -> None:
        """Admin: set an account's balance (never below 0)."""
        self._ensure(uid)
        self.eco.cur.execute("UPDATE bank_accounts SET balance=? WHERE user_id=?", (max(0, int(amount)), uid))
        self.eco.conn.commit()

    def rebind_casino(self, old: int, new: int) -> None:
        """The casino account moved to a new user id: carry its bank balance over."""
        have_new = self.eco.cur.execute("SELECT 1 FROM bank_accounts WHERE user_id=?", (new,)).fetchone()
        if have_new:
            self.eco.cur.execute("DELETE FROM bank_accounts WHERE user_id=?", (old,))
        else:
            self.eco.cur.execute("UPDATE bank_accounts SET user_id=? WHERE user_id=?", (new, old))
        self.eco.conn.commit()

    def _move(self, src: int, dst: int, amount: int) -> bool:
        if not _valid(amount) or src == dst or self.balance(src) < amount:
            return False
        self._ensure(dst)
        try:
            self.eco.cur.execute("UPDATE bank_accounts SET balance=balance-? WHERE user_id=?", (amount, src))
            self.eco.cur.execute("UPDATE bank_accounts SET balance=balance+? WHERE user_id=?", (amount, dst))
            self.eco.conn.commit()
        except Exception:
            self.eco.conn.rollback()
            raise
        return True

    def withdraw(self, uid: int, amount: int) -> bool:
        if helpers.TEST_MODE:  # infinite money: valid amounts always succeed and nothing moves
            return _valid(amount)
        return self._move(uid, self.eco.casino_user_id, amount)

    def deposit(self, uid: int, amount: int, kind: str = "sale") -> bool:
        if helpers.TEST_MODE:
            return _valid(amount)
        return self._move(self.eco.casino_user_id, uid, amount)


CENTS = 100  # economy.accounts.money is stored in cents; the Bank seam speaks whole dollars
CASINO_ACCOUNT_NAME = "Blue Horizon Casino"  # organization account that is the counterparty for every chip buy/cash-out

class SupabaseBank(Bank):
    """Bank money in the shared Supabase DB: a player's 'Main' account (found by discord_id) <-> the casino organization account.
    shortcut: synchronous psycopg calls on the event loop and one shared connection; use a pool/async driver if latency shows."""

    def __init__(self, url: str):
        self.url = url.replace('?ssl=', '?sslmode=').replace('&ssl=', '&sslmode=')  # asyncpg-style URLs (shared with the other bot) -> libpq
        self.conn = None
        self.casino_account = None
        self.casino_uid = helpers.CASINO_USER_ID  # follows rebind_casino

    def _db(self):
        import psycopg
        if self.conn is None or self.conn.closed:
            self.conn = psycopg.connect(self.url, autocommit=False, prepare_threshold=None)  # pooler: no prepared statements
        return self.conn

    def _run(self, fn):
        """Run fn(cursor) in one transaction; one retry on a dropped connection."""
        import psycopg
        for attempt in (0, 1):
            try:
                with self._db().cursor() as cur:
                    result = fn(cur)
                self.conn.commit()
                return result
            except psycopg.OperationalError:
                self.conn = None
                if attempt:
                    raise
            except Exception:
                self.conn.rollback()
                raise

    @staticmethod
    def _main_account(cur, uid: int):
        cur.execute("SELECT a.id, a.money FROM economy.accounts a JOIN public.identities_player p ON p.id = a.player_identity_id "
                    "WHERE p.discord_id = %s AND a.account_type = 'player' AND a.account_name = 'Main' AND a.archived_at IS NULL "
                    "ORDER BY a.id LIMIT 1", (uid,))
        return cur.fetchone()

    def _casino(self, cur) -> int:
        if self.casino_account is None:
            cur.execute("SELECT id FROM economy.accounts WHERE account_type = 'organization' AND account_name = %s "
                        "AND archived_at IS NULL", (CASINO_ACCOUNT_NAME,))
            row = cur.fetchone()
            if row is None:
                raise RuntimeError(f"No '{CASINO_ACCOUNT_NAME}' organization account in economy.accounts")
            self.casino_account = row[0]
        return self.casino_account

    def _cents(self, uid: int) -> int:
        row = self._run(lambda cur: self._main_account(cur, uid) if uid != self.casino_uid else self._casino_row(cur))
        return int(row[1]) if row else 0

    def balance(self, uid: int) -> int:
        if helpers.TEST_MODE:
            return TEST_MODE_BALANCE
        return self._cents(uid) // CENTS  # whole dollars; a sub-dollar remainder is not spendable

    def display(self, uid: int) -> str:
        if helpers.TEST_MODE:
            return super().display(uid)
        c = self._cents(uid)
        return f"${c // CENTS:,}.{c % CENTS:02d}"

    def _casino_row(self, cur):
        cur.execute("SELECT id, money FROM economy.accounts WHERE id = %s", (self._casino(cur),))
        return cur.fetchone()

    # Refusals the DB function raises on purpose (see sql/001_fab_casino_transfer.sql): the transfer did not happen.
    _REFUSED = ("insufficient_funds", "player_account_unavailable", "invalid_transfer")

    def _move(self, uid: int, amount: int, withdraw: bool, kind: str = None) -> bool:
        if not _valid(amount):
            return False
        key = f"casino-bot:{uuid.uuid4()}"  # one key per operation, so the retry in _run cannot charge twice
        args = (uid, amount * CENTS, "to_casino" if withdraw else "from_casino", "purchase" if withdraw else kind, key)

        def tx(cur):
            cur.execute("SELECT public.fab_casino_transfer(%s, %s, %s, %s, %s)", args)
            return True

        import psycopg
        try:
            return self._run(tx)
        except psycopg.Error as e:  # P0004/P0005 are not RaiseException subclasses
            if e.diag.message_primary in self._REFUSED:
                return False
            raise

    def withdraw(self, uid: int, amount: int) -> bool:
        if helpers.TEST_MODE:
            return _valid(amount)
        return self._move(uid, amount, True)

    def deposit(self, uid: int, amount: int, kind: str = "sale") -> bool:
        if helpers.TEST_MODE:
            return _valid(amount)
        return self._move(uid, amount, False, kind)

    def net_chip_money(self) -> int:
        """Cents the casino took in from chip buys minus cash-outs (bonuses excluded); see sql/002_fab_casino_chip_ledger.sql."""
        def q(cur):
            cur.execute("SELECT public.fab_casino_chip_ledger()")
            return int(cur.fetchone()[0]["net_cents"])
        return self._run(q)

    def set_balance(self, uid: int, amount: int) -> None:
        raise NotImplementedError("Bank money lives in Supabase; adjust it there (no silent edits from the bot).")

    def rebind_casino(self, old: int, new: int) -> None:
        self.casino_uid = new  # the money itself sits in the organization account, not under a Discord id
