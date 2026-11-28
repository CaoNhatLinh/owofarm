"""Count unanswered requests, then open a per-account cooldown circuit."""

import asyncio
import re
import time
from collections import deque

from utils import bot_control
from utils.command_pacing import CommandPacing
from utils.cooldown_feedback import CooldownFeedback, is_daily_wait
from utils.gamble_wallet import GambleWallet, INSUFFICIENT_WAGER_FUNDS
from utils.gambling_control import GAMES
from utils.weapon_equipment import extract_message_text


class ResponseGuard:
    def __init__(self, key, clock=time.monotonic, settings=bot_control.get_settings, *, channel_id=None):
        self.key = key
        self.label = "Tài khoản"
        self.channel_id = str(channel_id if channel_id is not None else key)
        self.channel_error = ""
        self.account_id = ""
        self.connected = False
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
        self.send_pacing = CommandPacing(clock=clock)
        self.cooldown_feedback = CooldownFeedback()
        self.gamble_wallet = GambleWallet()
        self._recent_requests = deque(maxlen=32)
        self._next_request = None
        self._early_replies = deque(maxlen=8)
        self._publish()

    def _publish(self):
        bot_control.publish_runtime(self.key, dict(name=self.label, misses=self.misses,
            accountId=self.account_id, connected=self.connected,
            channelId=self.channel_id, channelError=self.channel_error,
            activePrefix=self.prefix,
            captchaBlocked=self.captcha, scheduledSleep=self.scheduled_sleep,
            resumeGeneration=self.resume_generation,
            restUntil=time.time() + max(0, self.rest_until - self.clock()) if self.rest_until else 0,
            waitingForReply=self.pending is not None,
            gambleProfit=getattr(self, "gamble_profit", 0),
            gambleStreaks=getattr(self, "gamble_streaks", {}),
            coinflipAuto=getattr(self, "coinflip_auto", None),
            teamSetup=getattr(self, "team_setup_status", None),
            huntbotCaptcha=getattr(self, "huntbot_captcha", None),
            huntbotStatus=getattr(self, "huntbot_status", None),
            gambleLossStopped=getattr(self, "gamble_loss_stopped", False)))

    def tick(self):
        config = self.settings()
        now = self.clock()
        if not config["restEnabled"]:
            if self.pending and (not self.pending["manual"] or now >= self.pending["deadline"]):
                self.pending = None
            self.rest_until = 0
            self.misses = 0
        elif self.pending and not self.pending.get("manual", False) and not bot_control.is_running(self.account_id):
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

    def expect(self, channel_id, min_id=None, manual=False, command=None):
        config = self.settings()
        request = dict(channel_id=channel_id, sent_id=None, manual=manual, command=command,
            min_id=min_id if min_id is not None else ((int(time.time() * 1000) - 1420070400000) << 22),
            deadline=self.clock() + config["responseTimeout"])
        self._next_request = request
        if not manual and not config["restEnabled"]:
            return
        self.pending = request
        self._publish()

    def sent(self, message, command=None, cooldown=0, channel_id=None, message_id=None):
        self.last_sent = self.clock()
        request = self._next_request or self.pending or {}
        if command is None:
            command = request.get("command")
        if channel_id is None:
            channel_id = getattr(getattr(message, "channel", None), "id", None) or request.get("channel_id", self.channel_id)
        if message_id is None:
            message_id = getattr(message, "id", None)
        self.send_pacing.sent(command=command, cooldown=cooldown, channel_id=channel_id, message_id=message_id)
        if self.pending and str(channel_id) == str(self.pending["channel_id"]) and message_id is not None:
            self.pending["sent_id"] = message_id
        self._recent_requests.append(dict(
            channel_id=channel_id, sent_id=message_id, command=command,
            min_id=message_id if message_id is not None else request.get("min_id", ((int(time.time() * 1000) - 1420070400000) << 22)),
            deadline=self.clock() + self.settings()["responseTimeout"],
        ))
        self._next_request = None
        early_replies = list(self._early_replies)
        self._early_replies.clear()
        for reply in early_replies:
            self.observe(*reply)
        self._publish()

    def cancel(self):
        self.pending = None
        self._next_request = None
        self._early_replies.clear()
        self._publish()

    def observe(self, message, owner_id, names, owo_id):
        self.tick()
        if getattr(getattr(message, "author", None), "id", None) != owo_id:
            return False
        channel_id = getattr(getattr(message, "channel", None), "id", None) or getattr(message, "channel_id", None)
        reference = getattr(message, "reference", None)
        ref_id = getattr(reference, "message_id", None)
        text = extract_message_text(message)
        funds_text = re.sub(r"<a?:cowoncy:\d+>", "cowoncy", text, flags=re.I)
        funds_error = INSUFFICIENT_WAGER_FUNDS.search(re.sub(r"[*`~_]", "", funds_text))
        mentions = set(re.findall(r"<@!?(\d+)>", text))
        if mentions:
            owned = str(owner_id) in mentions
        else:
            plain = re.sub(r"[*~`]", "", text).casefold()
            owned = any(re.search(r"(?<!\w)" + re.escape(name.casefold()) + r"(?!\w)", plain) for name in names if name)
        message_id = int(getattr(message, "id", 0))
        if ref_id is None and is_daily_wait(text):
            if not owned or str(channel_id) != self.channel_id:
                return False
            feedback = self.cooldown_feedback.apply(message_id, text, "daily", self.send_pacing)
            # A manually requested daily can answer while a hunt or battle is pending.
            if self.pending is None or self.pending.get("command") != "daily":
                return feedback
        request = self._next_request
        if (request and request["sent_id"] is None
                and (self.pending is None or (funds_error and request["command"] in GAMES))
                and str(channel_id) == str(request["channel_id"]) and self.clock() < request["deadline"]
                and message_id >= request["min_id"]
                and ((ref_id is None and owned) or (ref_id is not None and request["min_id"] <= ref_id <= message_id))):
            # Failure-rest may be off, but feedback still needs the successful send ID.
            self._early_replies.append((message, owner_id, names, owo_id))
            return False
        requests = ([self.pending] if self.pending is not None else []) + list(reversed(self._recent_requests))
        matched = None
        eligible_commands = set()
        for request in requests:
            if (str(channel_id) != str(request["channel_id"]) or self.clock() >= request["deadline"]
                    or message_id < (request["sent_id"] or request["min_id"])):
                continue
            if (ref_id is not None and ref_id == request["sent_id"]) or (ref_id is None and owned):
                if matched is None:
                    matched = request
                eligible_commands.add(request.get("command"))
        if matched is None:
            # A referenced response can arrive before channel.send returns its ID.
            request = self._next_request
            if (request and ref_id is not None and request["sent_id"] is None
                    and str(channel_id) == str(request["channel_id"])
                    and request["min_id"] <= ref_id <= message_id and self.clock() < request["deadline"]):
                self._early_replies.append((message, owner_id, names, owo_id))
            return False
        feedback_command = matched.get("command")
        if ref_id is None and self.pending is None and len(eligible_commands) > 1:
            # Without a reply reference, several recent command kinds are ambiguous.
            feedback_command = None
        if funds_error and feedback_command in GAMES and matched["sent_id"] is not None:
            self.gamble_wallet.invalidate(message_id)
        feedback = self.cooldown_feedback.apply(message_id, text, feedback_command, self.send_pacing)
        acknowledged = matched is self.pending
        if acknowledged:
            self.pending = None
            self.misses = 0
        self._publish()
        return acknowledged or feedback

    async def wait_ready(self, manual=False):
        while not self.ready or (not manual and not bot_control.is_running(self.account_id)):
            await asyncio.sleep(.25)
