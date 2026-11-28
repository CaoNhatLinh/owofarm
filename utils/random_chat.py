"""Occasional idle chatter through the normal account send controls."""

import random
import time
from collections import deque

from utils import bot_control
from utils.command_timing import command_timing


PHRASES = (
    "hmm", "ờ để xem", "ừm...", "chờ chút", "vẫn ổn", "nghĩ chút đã",
    "à ra vậy", "hơi buồn ngủ", "lại tiếp thôi", "từ từ nào", "đang suy nghĩ", "...",
    "ngồi chơi xíu", "cũng được đó", "thôi kệ", "vậy nha",
)


class RandomChat:
    INTERVAL = (120.0, 360.0)

    def __init__(self, bot, clock=time.monotonic, rng=None):
        self.bot = bot
        self.clock = clock
        self.random = rng if rng is not None else random.Random()
        self.next_at = None
        self.recent_phrases = deque(maxlen=3)

    def _schedule(self):
        self.next_at = self.clock() + self.random.uniform(*self.INTERVAL)

    def phrase_allowed(self, phrase):
        if command_timing(self.bot, phrase)[0] is not None:
            return False
        text_commands = getattr(getattr(self.bot, "global_settings_dict", None), "textCommands", None)
        prefix = getattr(text_commands, "prefix", "")
        for setting in ("stopCommand", "startCommand", "sleepCommand", "restartCommand", "switchChannelCommand"):
            command = getattr(text_commands, setting, None)
            if isinstance(command, str) and phrase.casefold().startswith((prefix + command).casefold()):
                return False
        return True

    def can_send(self, channel, prefix, phrase=None):
        settings = bot_control.settings_for(self.bot)
        if not settings.get("randomChatEnabled", False) or not bot_control.running_for(self.bot):
            return False
        status = self.bot.ch.command_handler_status
        if (not status.state or status.hold_handler or status.sleep or status.captcha
                or not self.bot.ch.queue.empty() or not self.bot.response_guard.ready):
            return False
        manager = self.bot.get_cog("Commands")
        if manager is not None and getattr(manager, "_inflight_command_id", None) is not None:
            return False
        if (channel is None or getattr(self.bot.cm, "id", None) != channel.id
                or self.bot.settings_dict.prefix != prefix or settings.get("prefix", prefix) != prefix):
            return False
        configured_channel = settings.get("channelId") or getattr(self.bot, "_initial_channel_id", channel.id)
        if str(configured_channel) != str(channel.id):
            return False
        interval = max(settings["messageInterval"], getattr(channel, "slowmode_delay", getattr(self.bot, "cm_slowmode_cd", 0)))
        guard = self.bot.response_guard
        if guard.send_pacing.remaining(interval) > 0:
            return False
        if guard.clock() - guard.last_sent < interval:
            return False
        return phrase is None or self.phrase_allowed(phrase)

    async def tick(self):
        if not bot_control.settings_for(self.bot).get("randomChatEnabled", False):
            self.next_at = None
            return False
        if self.next_at is None:
            self._schedule()
            return False
        if self.clock() < self.next_at:
            return False
        channel = self.bot.cm
        prefix = self.bot.settings_dict.prefix
        if self.bot._outgoing_lock.locked() or not self.can_send(channel, prefix):
            return False
        candidates = [phrase for phrase in PHRASES if phrase not in self.recent_phrases and self.phrase_allowed(phrase)]
        if not candidates:
            self._schedule()
            return False
        phrase = self.random.choice(candidates)
        # Schedule once for the attempt; a failed send never creates a retry burst.
        self._schedule()
        sent = await self.bot.send(
            phrase, channel=channel, expect_response=False, typingIndicator=False,
            automation_check=lambda: self.can_send(channel, prefix, phrase),
        )
        if sent:
            self.recent_phrases.append(phrase)
        return bool(sent)
