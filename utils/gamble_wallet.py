"""Track confirmed Cowoncy balances separately from local balance estimates."""

import re

INSUFFICIENT_WAGER_FUNDS = re.compile(
    r"\b(?:(?:insufficient|not enough)\s+(?:cowoncy|cash|money|funds)|"
    r"(?:don['’]t|do not)\s+have\s+(?:that much|(?:enough|any)\s+(?:cowoncy|cash|money|funds)))\b",
    re.I,
)


class GambleWallet:
    def __init__(self):
        self.confirmed_id = 0
        self.rejected_id = 0
        self.confirmed_amount = 0
        self.unaffordable = set()
        self.last_requested = float("-inf")

    def invalidate(self, message_id):
        self.rejected_id = max(self.rejected_id, message_id)

    def confirm(self, message_id, amount):
        if message_id <= max(self.confirmed_id, self.rejected_id):
            return False
        self.confirmed_id = message_id
        self.confirmed_amount = amount
        self.unaffordable.clear()
        return True

    def waiting(self, game=None):
        return (self.confirmed_id <= self.rejected_id
                or None in self.unaffordable or game in self.unaffordable
                or (game is None and bool(self.unaffordable)))

    def blocks(self, amount, balance, game):
        if self.waiting(game):
            return True
        if amount > (self.confirmed_amount if balance is None else balance):
            self.unaffordable.add(game)
            return True
        return False
