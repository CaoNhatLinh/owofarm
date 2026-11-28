"""Monotonic command deadlines, account spacing, jitter, and bounded rests."""

import random
import time
from collections import deque


class CommandPacing:
    JITTER = (0.4, 2.0)
    FAST_WINDOW = 45.0
    BURST_SIZE = (6, 9)
    SHORT_REST = (2.0, 20.0)
    REST_CHANCE = 0.1
    SAFETY_MARGIN = 0.5

    def __init__(self, clock=time.monotonic, rng=None):
        self.clock = clock
        self.random = rng if rng is not None else random.Random()
        self.last_sent = float("-inf")
        self.jitter = 0.0
        self.rest_until = 0.0
        self.recent_sends = deque(maxlen=self.BURST_SIZE[1])
        self.burst_size = self.random.randint(*self.BURST_SIZE)
        self.command_sends = {}
        self.deferred_until = {}

    def sent(self, command=None, cooldown=0, channel_id=None, message_id=None):
        """Record only successful sends; sample once for the next send slot."""
        now = self.clock()
        self.last_sent = now
        self.jitter = self.random.uniform(*self.JITTER)
        if command is not None and cooldown > 0:
            # Keep the sample fixed for this send, including retries and aliases.
            padding = self.SAFETY_MARGIN + self.random.uniform(0.0, min(10.0, max(0.0, cooldown)))
            self.command_sends[command] = (now, max(0.0, cooldown), padding)
        while self.recent_sends and now - self.recent_sends[0] >= self.FAST_WINDOW:
            self.recent_sends.popleft()
        self.recent_sends.append(now)
        if len(self.recent_sends) >= self.burst_size or self.random.random() < self.REST_CHANCE:
            self.rest_until = now + self.random.uniform(*self.SHORT_REST)
            self.recent_sends.clear()
            self.burst_size = self.random.randint(*self.BURST_SIZE)

    def defer(self, command, seconds):
        """Server feedback may extend a deadline, never shorten it."""
        self.deferred_until[command] = max(
            self.deferred_until.get(command, 0.0), self.clock() + max(0.0, seconds),
        )

    def remaining(self, minimum_interval, command=None, minimum_cooldown=0):
        """Extra pacing never reduces configured spacing or channel slowmode."""
        now = self.clock()
        command_deadline = self.deferred_until.get(command, 0.0)
        previous = self.command_sends.get(command)
        if previous is not None:
            sent_at, sampled_minimum, padding = previous
            command_deadline = max(
                command_deadline, sent_at + max(sampled_minimum, minimum_cooldown) + padding,
            )
        return max(
            0.0,
            self.last_sent + minimum_interval + self.jitter - now,
            self.rest_until - now,
            self.deferred_until.get(None, 0.0) - now,
            command_deadline - now,
        )
