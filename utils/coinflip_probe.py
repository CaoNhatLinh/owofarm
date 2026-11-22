"""Stateful Coinflip side rules, without any claimed predictive accuracy."""
import re
import secrets
from utils.coinflip_history import chosen_side


class ProbePlan:
    def __init__(self, kind="random", target="heads"):
        self.kind, self.target = kind, target
        self.epoch = 0
        self.reset()

    def reset(self):
        self.epoch += 1
        self.phase = "wager" if self.kind == "win_switch" else "probe"
        if self.kind in ("win_switch", "until_loss"):
            self.side = self.target
        else:
            self.side = "heads"

    def configure(self, kind, target):
        self.kind, self.target = kind, target
        self.reset()

    def snapshot(self):
        return dict(phase=self.phase, side=self.side)

    def complete(self, won, choose=None):
        if self.kind == "win_switch":
            if won:
                self.side = "tails" if self.side == "heads" else "heads"
            return
        if self.phase == "probe":
            if self.kind == "until_loss":
                if not won:
                    self.side = self.target
                    self.phase = "wager"
                return
            random_side = (choose or (lambda: secrets.choice(("heads", "tails"))))()
            self.side = ("tails" if random_side == "heads" else "heads") if won else random_side
            self.phase = "wager"
        else:
            self.reset()


def get_plan(bot):
    if not hasattr(bot, "coinflip_probe"):
        bot.coinflip_probe = ProbePlan()
    return bot.coinflip_probe


def matching_pending(bot, content):
    pending = getattr(bot, "_coinflip_pending", None)
    text = re.sub(r"<a?:\w+:\d+>", "", content or "")
    text = re.sub(r"[*`_]", "", text)
    stake = re.search(r"\bspent\s+([\d,]+)", text, re.I)
    if pending and stake and int(stake[1].replace(",", "")) == pending["stake"] and chosen_side(content) == pending["side"]:
        return pending
    return {}


def is_probe_result(bot, content):
    return matching_pending(bot, content).get("probe", False)


def complete_result(bot, content, outcome):
    pending = matching_pending(bot, content)
    if not pending:
        return
    # A mode switch must not carry an old probe into a new cycle.
    plan = get_plan(bot)
    if pending["mode"] in ("probe", "probe_loss", "win_switch") and getattr(bot, "_coinflip_active_mode", None) == pending["mode"] and pending.get("planVersion", plan.epoch) == plan.epoch:
        plan.complete(outcome == "win")
    bot._coinflip_pending = None
