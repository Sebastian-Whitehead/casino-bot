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


def _valid(amount) -> bool:
    return type(amount) is int and amount > 0


class LocalBank(Bank):
    """Bank backed by the `money` column of economy.db; the casino account is the counterparty."""

    def __init__(self, economy):
        self.eco = economy

    def balance(self, uid: int) -> int:
        return self.eco.get_entry(uid)[1]

    def _move(self, src: int, dst: int, amount: int) -> bool:
        if not _valid(amount) or src == dst or self.balance(src) < amount:
            return False
        self.eco.get_entry(dst)  # make sure the row exists
        try:
            self.eco.cur.execute("UPDATE economy SET money=money-? WHERE user_id=?", (amount, src))
            self.eco.cur.execute("UPDATE economy SET money=money+? WHERE user_id=?", (amount, dst))
            self.eco.conn.commit()
        except Exception:
            self.eco.conn.rollback()
            raise
        return True

    def withdraw(self, uid: int, amount: int) -> bool:
        return self._move(uid, self.eco.casino_user_id, amount)

    def deposit(self, uid: int, amount: int) -> bool:
        return self._move(self.eco.casino_user_id, uid, amount)
