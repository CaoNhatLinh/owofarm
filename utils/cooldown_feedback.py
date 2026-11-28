"""Recognize explicit server cooldown notices and apply bounded backoff."""

import math
import re
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class CooldownNotice:
    seconds: float | None
    account_wide: bool = False


_CUE = re.compile(r"\b(?:slow\s+down|cool\s*down|wait|try\s+again\s+in)\b", re.I)
_DAILY_WAIT = re.compile(r"^\s*⏱\ufe0f?\s*\|\s*nu!\s+[^\n]+?!\s+you need to wait\s+\d", re.I)
_DURATION = re.compile(
    r"(?<![\w.+-])(\d+(?:\.\d+)?)\s*(?:more\s+)?"
    r"(hours?|hrs?|h|minutes?|mins?|m|seconds?|secs?|s)\b", re.I,
)


def is_daily_wait(text):
    return _DAILY_WAIT.match(re.sub(r"[*~`_]", "", text)) is not None


def parse_cooldown(text):
    """Ignore ordinary result amounts unless an explicit waiting cue precedes time."""
    plain = re.sub(r"<a?:\w+:\d+>", "", text or "")
    plain = re.sub(r"[*~`_]", "", plain)
    cue = _CUE.search(plain)
    if cue is None:
        return None
    if cue.group().casefold() == "wait" and not re.match(
        r"\s+(?:(?:for|another|about|at\s+least)\s+){0,2}\d", plain[cue.end():], re.I,
    ):
        return None
    if re.search(r"\bcool\s*down\s+(?:reduced|decreased|boost|bonus|upgrade)\b", plain, re.I):
        return None
    # Do not borrow numbers from a later result paragraph or unrelated sentence.
    tail = re.split(r"[\n!?]", plain[cue.end():], maxsplit=1)[0][:160]
    durations = list(_DURATION.finditer(tail))
    if not durations and cue.group().casefold() == "slow down":
        # A common notice is "Slow down! Please wait 5 seconds."
        followup = plain[cue.end():].lstrip("!?. ")
        if re.match(r"(?:please\s+)?wait\b", followup, re.I):
            tail = followup[:160]
            durations = list(_DURATION.finditer(tail))
    if durations:
        seconds = 0.0
        previous = None
        for duration in durations:
            if previous is not None and re.sub(r"[\s,]|\band\b", "", tail[previous.end():duration.start()], flags=re.I):
                break
            value, unit = duration.groups()
            factor = 3600 if unit.lower().startswith("h") else 60 if unit.lower().startswith("m") else 1
            seconds += float(value) * factor
            previous = duration
        if not math.isfinite(seconds):
            return None
        return CooldownNotice(seconds, account_wide=bool(re.search(r"\bslow\s+down\b", plain, re.I)))
    if re.fullmatch(r"slow\s+down|cool\s*down", cue.group(), re.I):
        return CooldownNotice(None)
    return None


class CooldownFeedback:
    """Deduplicate native/raw/edit notices without retrying any action."""

    def __init__(self):
        self.backoff_count = 0
        self._seen_notices = deque(maxlen=128)
        self._seen_successes = deque(maxlen=128)

    def apply(self, message_id, text, command, pacing):
        notice = parse_cooldown(text)
        if notice is not None:
            if message_id not in self._seen_notices:
                self._seen_notices.append(message_id)
                if notice.seconds is None:
                    self.backoff_count = min(self.backoff_count + 1, 6)
                    pacing.defer(None, min(60.0, 2.0 ** self.backoff_count))
                elif notice.account_wide or command is not None:
                    pacing.defer(None if notice.account_wide else command, notice.seconds + 0.5)
                else:
                    # An unlinked command timer is not evidence of an account-wide cooldown.
                    pacing.defer(None, min(60.0, notice.seconds + 0.5))
            return True
        if text.strip() and not _CUE.search(text) and message_id not in self._seen_successes:
            self._seen_successes.append(message_id)
            self.backoff_count = 0
        return False
