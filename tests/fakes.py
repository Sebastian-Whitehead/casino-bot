"""In-memory stand-in for Economy's chip and wager API (same semantics, no sqlite)."""
from modules.helpers import InsufficientFundsException


class FakeEconomy:
    def __init__(self, chips, user_id=1):
        self.chips = {user_id: chips, "casino": 0}
        self.wagers = {}  # (game_id, uid) -> {"amount", "status"}

    def get_chips(self, uid):
        return self.chips[uid]

    def place_bet(self, uid, n):
        assert n > 0 and self.chips[uid] >= n
        self.chips[uid] -= n
        self.chips["casino"] += n

    def pay_out(self, uid, n):
        self.chips["casino"] -= n
        self.chips[uid] += n

    def open_wager(self, game_id, uid, game, amount):
        if self.chips[uid] < amount:
            raise InsufficientFundsException(self.chips[uid], amount)
        assert (game_id, uid) not in self.wagers, "duplicate wager"
        self.place_bet(uid, amount)
        self.wagers[(game_id, uid)] = {"amount": amount, "status": "open"}

    def _close(self, game_id, uid, status, payout):
        w = self.wagers[(game_id, uid)]
        if w["status"] != "open":
            return False
        w["status"] = status
        if payout:
            self.pay_out(uid, payout)
        return True

    def settle_wager(self, game_id, uid, payout):
        return self._close(game_id, uid, "settled", payout)

    def refund_wager(self, game_id, uid):
        return self._close(game_id, uid, "refunded", self.wagers[(game_id, uid)]["amount"])

    def open_count(self):
        return sum(1 for w in self.wagers.values() if w["status"] == "open")
