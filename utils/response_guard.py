"""Count unanswered requests, then open a per-account cooldown circuit."""

import asyncio
import re
import time

from utils import bot_control
from utils.weapon_equipment import extract_message_text


class ResponseGuard:
    def __init__(self, key, clock=time.monotonic, settings=bot_control.get_settings):
        self.key = key
        self.label = "Tài khoản"
        self.channel_id = str(key)
        self.channel_error = ""
        self.prefix = ""
        self.captcha = False
        self.scheduled_sleep = False
        self.resume_generation = bot_control.get_resume_generation()
        self.clock = clock
        self.settings = settings
        self.misses = 0
        self.rest_until = 0
        self.pending = None
        self.last_sent = float("-inf")
        self._publish()

    def _publish(self):
        bot_control.publish_runtime(self.key, dict(name=self.label, misses=self.misses,
            accountId=getattr(self, "account_id", ""),
            channelId=self.channel_id, channelError=self.channel_error,
            activePrefix=self.prefix,
            captchaBlocked=self.captcha, scheduledSleep=self.scheduled_sleep,
            resumeGeneration=self.resume_generation,
            restUntil=time.time() + max(0, self.rest_until - self.clock()) if self.rest_until else 0,
            waitingForReply=self.pending is not None,
            gambleProfit=getattr(self, "gamble_profit", 0),
            gambleStreaks=getattr(self, "gamble_streaks", {}),
            coinflipAuto=getattr(self, "coinflip_auto", None),
            gambleLossStopped=getattr(self, "gamble_loss_stopped", False)))

    def tick(self):
        config = self.settings()
        now = self.clock()
        if not config["restEnabled"]:
            self.pending = None
            self.rest_until = 0
            self.misses = 0
        elif not bot_control.is_running() and self.pending and not self.pending.get("manual", False):
            self.pending = None  # Pausing farm does not cancel a manual operation.
        elif self.rest_until:
            if now >= self.rest_until:
                self.rest_until = 0
                self.misses = 0
        elif self.pending and now >= self.pending["deadline"]:
            self.pending = None
            self.misses += 1
            if self.misses >= config["failureThreshold"]:
                self.rest_until = now + config["restMinutes"] * 60
        elif self.misses >= config["failureThreshold"]:
            self.rest_until = now + config["restMinutes"] * 60
        self._publish()

    @property
    def cooling_down(self):
        self.tick()
        return self.rest_until > self.clock()

    @property
    def ready(self):
        self.tick()
        return not self.pending and not self.rest_until

    def expect(self, channel_id, min_id=None, manual=False):
        if not self.settings()["restEnabled"]:
            return
        self.pending = dict(channel_id=channel_id, sent_id=None, manual=manual,
            min_id=min_id if min_id is not None else ((int(time.time() * 1000) - 1420070400000) << 22),
            deadline=self.clock() + self.settings()["responseTimeout"])
        self._publish()

    def sent(self, message):
        self.last_sent = self.clock()
        if self.pending and message is not None:
            self.pending["sent_id"] = message.id
        self._publish()

    def cancel(self):
        self.pending = None
        self._publish()

    def observe(self, message, owner_id, names, owo_id):
        self.tick()
        pending = self.pending
        if not pending or getattr(getattr(message, "author", None), "id", None) != owo_id:
            return False
        channel_id = getattr(getattr(message, "channel", None), "id", None) or getattr(message, "channel_id", None)
        if channel_id != pending["channel_id"] or int(getattr(message, "id", 0)) < (pending["sent_id"] or pending["min_id"]):
            return False
        reference = getattr(message, "reference", None)
        ref_id = getattr(reference, "message_id", None)
        text = extract_message_text(message)
        mentions = set(re.findall(r"<@!?(\d+)>", text))
        if ref_id is not None:
            owned = ref_id == pending["sent_id"]
        elif mentions:
            owned = str(owner_id) in mentions
        else:
            plain = re.sub(r"[*~`]", "", text).casefold()
            owned = any(re.search(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", plain) for name in names if name)
        if not owned:
            return False
        self.pending = None
        self.misses = 0
        self._publish()
        return True

    async def wait_ready(self, manual=False):
        while not self.ready or (not manual and not bot_control.is_running()):
            await asyncio.sleep(.25)
