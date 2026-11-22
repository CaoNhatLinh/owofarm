"""Per-account game spacing, shared by normal sends and retries."""
import time
from collections import deque


class GamblePacing:
    def __init__(self, clock=time.monotonic, startup_delay=0):
        self.clock = clock
        self.ready_at = {game: clock() + startup_delay for game in ("coinflip", "slots", "blackjack")} if startup_delay else {}
        self.versions = {}
        self.completed = set()
        self.history = deque()

    def remaining(self, game):
        return max(0, self.ready_at.get(game, 0) - self.clock())

    def version(self, game):
        return self.versions.get(game, 0)

    def sent(self, game):
        self.ready_at[game] = max(self.ready_at.get(game, 0), self.clock() + 10)

    def finish(self, game, message_id):
        key = (game, message_id)
        if key in self.completed:
            return False
        self.completed.add(key)
        self.history.append(key)
        if len(self.history) > 1024:
            self.completed.discard(self.history.popleft())
        self.sent(game)
        self.versions[game] = self.version(game) + 1
        return True
