class Bank:
    """Bank-money seam. Swap LocalBank for a Supabase implementation later."""

    def balance(self, uid: int) -> int:
        raise NotImplementedError

    def withdraw(self, uid: int, amount: int) -> bool:
        """Take amount from the player. False if amount <= 0 or funds are short; never partial."""
        raise NotImplementedError

    def deposit(self, uid: int, amount: int) -> bool:
        """Give amount to the player. False if amount <= 0 or the source cannot pay."""
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

    def deposit(self, uid: int, amount: int) -> bool:
        if helpers.TEST_MODE:
            return _valid(amount)
        return self._move(self.eco.casino_user_id, uid, amount)
