"""Dashboard switches and lifecycle for the three optional games."""
import asyncio
import re
import sqlite3
import time

from utils import bot_control

GAMES = ("coinflip", "slots", "blackjack")
COG_NAMES = dict(coinflip="Coinflip", slots="Slots", blackjack="Blackjack")
COG_STARTERS = dict(coinflip="start_cf", slots="start_slots", blackjack="send_blackjack")
WALLET_CHECK_INTERVAL = 60


def enabled(game, bot=None):
    if game == "gems":
        from utils.gem_control import enabled as gems_enabled
        return gems_enabled(bot)
    if game in ("hunt", "battle"):
        from utils.farm_control import enabled as farm_enabled
        return farm_enabled(game, bot)
    return bot_control.settings_for(bot)[game + "Enabled"] if game in GAMES else True


def command_allowed(message, prefix, aliases, bot=None):
    from utils.gem_control import command_allowed as gems_allowed
    if not gems_allowed(message, prefix, aliases, bot):
        return False
    from utils.farm_control import command_allowed as farm_allowed
    if not farm_allowed(message, prefix, aliases, bot):
        return False
    game = command_game(message, prefix, aliases)
    return enabled(game, bot) and (game is None or not wallet_waiting(bot, game))


def command_game(message, prefix, aliases):
    if not message.startswith(prefix):
        return None
    parts = message[len(prefix):].split()
    if not parts:
        return None
    for game in GAMES:
        names = {game, {"coinflip": "cf", "slots": "s", "blackjack": "bj"}[game]}
        names.update(value for value in aliases.get(game, {}).values() if isinstance(value, str))
        if parts[0].casefold() in names:
            return game
    return None


def stake_for_losses(base, losses, doubling, bonus=False):
    if not doubling:
        return base
    # Even a base of 1 exceeds the live cap by the 18th consecutive loss.
    losses = min(max(0, losses), 18)
    if not bonus:
        return base * 2 ** losses
    stake = base
    for step in range(losses):
        stake = stake * (200 + 10 * step) // 100
    return stake


def bet_amount(game, losses=0, bot=None):
    config = bot_control.settings_for(bot)
    return stake_for_losses(config[game + "Bet"], losses, config[game + "DoubleOnLoss"],
                            game == "coinflip" and config.get("coinflipBonusOnLoss", False))


def goal_reached(bot):
    config = bot_control.settings_for(bot)
    return config["gambleGoalEnabled"] and bot.stats.gain_or_lose >= config["gambleGoalAmount"]


def loss_blocked(bot, next_bet=0):
    config = bot_control.settings_for(bot)
    if not config["gambleLossEnabled"]:
        bot._gamble_loss_latch = None
        return False
    profit = bot.stats.gain_or_lose
    limit = config["gambleLossAmount"]
    if getattr(bot, "_gamble_loss_latch", None) == limit:
        return True
    bot._gamble_loss_latch = None
    if profit <= -limit:
        bot._gamble_loss_latch = limit
        return True
    return profit - next_bet < -limit


def _wallet(bot):
    return getattr(getattr(bot, "response_guard", None), "gamble_wallet", None)


def wallet_waiting(bot, game=None):
    wallet = _wallet(bot)
    return wallet is not None and wallet.waiting(game)


def invalidate_wallet(bot, message_id):
    wallet = _wallet(bot)
    if wallet is not None:
        wallet.invalidate(message_id)


def confirm_wallet(bot, message_id, amount):
    wallet = _wallet(bot)
    return wallet is None or wallet.confirm(message_id, amount)


def balance_blocks(bot, amount, game=None):
    balance = bot.stats.balance if getattr(bot.stats, "has_updated_balance", False) else None
    wallet = _wallet(bot)
    return wallet.blocks(amount, balance, game) if wallet is not None else balance is not None and amount > balance


async def request_wallet_check(bot):
    wallet = _wallet(bot)
    if (wallet is None or not wallet.waiting() or not any(enabled(game, bot) for game in GAMES)
            or not getattr(bot, "cm", None) or bot.ch.should_not_send):
        return
    now = time.monotonic()
    if now - wallet.last_requested < WALLET_CHECK_INTERVAL or bot.ch.cmds_state.get("cash", {}).get("in_queue"):
        return
    queued = await bot.ch.put_queue({
        "cmd_name": bot.alias.get("cash", {}).get("normal", "cash"),
        "prefix": True, "checks": False, "id": "cash",
    }, wait=False)
    if queued:
        wallet.last_requested = now


def blackjack_profit(description, payout, fallback_stake):
    text = re.sub(r"<a?:\w+:\d+>", "", description or "")
    match = re.search(r"\byou bet\s*[*`]*\s*([\d,]+)", text, re.I)
    stake = int(match[1].replace(",", "")) if match else fallback_stake
    return payout - stake


def refresh_message_bet(bot, message):
    game = command_game(message, bot.settings_dict.prefix, bot.alias)
    if game is None:
        return message
    if goal_reached(bot):
        return None
    apply_flags(bot)
    cog = bot.get_cog(COG_NAMES[game])
    amount = bet_amount(game, getattr(cog, "turns_lost", 0), bot)
    if balance_blocks(bot, amount, game):
        return None
    mode = bot_control.settings_for(bot)["coinflipSide"] if game == "coinflip" else None
    probe = False
    if mode in ("probe", "probe_loss"):
        from utils.coinflip_probe import get_plan
        # Never spend a probe when the next main stake is already impossible.
        if amount > 250000 or loss_blocked(bot, amount):
            return None
        probe = get_plan(bot).phase == "probe"
        if probe:
            amount = 1
    if amount > 250000 or loss_blocked(bot, amount):
        return None
    prefix = bot.settings_dict.prefix
    parts = message[len(prefix):].split()
    if len(parts) < 2 or not parts[1].isdigit():
        return message
    parts[1] = str(amount)
    if game == "coinflip":
        # Read again immediately before sending, including queued retries.
        from utils.coinflip_history import select_side
        parts[2:] = [select_side(bot, mode)]
        bot._coinflip_prepared = dict(mode=mode, probe=probe, side=parts[2], stake=amount)
        if mode in ("probe", "probe_loss", "win_switch"):
            from utils.coinflip_probe import get_plan
            bot._coinflip_prepared["planVersion"] = get_plan(bot).epoch
    return prefix + " ".join(parts)


def apply_flags(bot):
    config = bot_control.settings_for(bot)
    target = config["coinflipSwitchStart"] if config["coinflipSide"] == "win_switch" else config["coinflipProbeTarget"]
    if getattr(bot, "_coinflip_active_mode", None) != config["coinflipSide"] or (config["coinflipSide"] in ("probe_loss", "win_switch") and getattr(bot, "_coinflip_probe_target", None) != target):
        from utils.coinflip_probe import get_plan
        kind = {"probe_loss":"until_loss", "win_switch":"win_switch"}.get(config["coinflipSide"], "random")
        get_plan(bot).configure(kind, target)
        bot._coinflip_active_mode = config["coinflipSide"]
        bot._coinflip_probe_target = target
    goals = getattr(bot.settings_dict.gamble, "goals", None)
    if goals:
        goals.enabled, goals.amount = config["gambleGoalEnabled"], config["gambleGoalAmount"]
    bot.settings_dict.gamble.allottedAmount = config["gambleLossAmount"]
    for game in GAMES:
        settings = getattr(bot.settings_dict.gamble, game)
        settings.enabled = config[game + "Enabled"]
        base, multiplier = config[game + "Bet"], 2 if config[game + "DoubleOnLoss"] else 1
        changed = (getattr(settings, "startValue", base), getattr(settings, "multiplier", multiplier)) != (base, multiplier)
        settings.startValue, settings.multiplier = base, multiplier
        if game == "coinflip":
            bonus = multiplier == 2 and config.get("coinflipBonusOnLoss", False)
            changed |= getattr(settings, "bonusOnLoss", False) != bonus
            settings.bonusOnLoss = bonus
        cog = bot.get_cog(COG_NAMES[game]) if changed else None
        if cog:
            if cog.exceeded_max_amount:
                cog._restart_after_cap = True
            cog.turns_lost = 0
            cog.exceeded_max_amount = False


def restart_game(cog, game):
    cog._restart_after_cap = False
    starter = getattr(cog, COG_STARTERS[game])
    cog.start_gambling(starter(startup=True))


async def sync(bot):
    apply_flags(bot)
    for game in GAMES:
        extension = "core.cogs." + game
        if enabled(game, bot):
            if extension not in bot.extensions:
                await bot.load_extension(extension)
            else:
                cog = bot.get_cog(COG_NAMES[game])
                if getattr(cog, "_restart_after_cap", False):
                    restart_game(cog, game)
        elif extension in bot.extensions:
            await bot.unload_extension(extension)


async def discard(bot, game):
    async with bot.ch._hold_or_create_lock():
        kept = []
        while not bot.ch.queue.empty():
            item = bot.ch.queue.get_nowait()
            if item[2].get("id") != game:
                kept.append(item)
        for item in kept:
            bot.ch.queue.put_nowait(item)
        bot.ch.checks[:] = [c for c in bot.ch.checks if c.get("id") != game]
        if game in bot.ch.cmds_state:
            bot.ch.cmds_state[game]["in_queue"] = False


class GamblingLifecycle:
    """Cancel startup/retry tasks and prevent old listeners from requeueing."""
    def gambling_enabled(self):
        return getattr(self, "_gambling_alive", True) and enabled(self.cmd["id"], self.bot)

    def profit_goal_reached(self):
        return goal_reached(self.bot)

    async def wait_for_profit_goal(self):
        while self.gambling_enabled() and self.profit_goal_reached():
            await asyncio.sleep(0.5)

    def balance_blocks(self, amount):
        return balance_blocks(self.bot, amount, self.cmd["id"])

    async def wait_for_balance(self):
        game = self.cmd["id"]
        while self.gambling_enabled() and self.balance_blocks(bet_amount(game, self.turns_lost, self.bot)):
            await asyncio.sleep(0.5)

    def loss_limit_blocks(self, amount):
        return loss_blocked(self.bot, amount)

    async def wait_for_loss_limit(self):
        while self.gambling_enabled() and loss_blocked(self.bot, bet_amount(self.cmd["id"], self.turns_lost, self.bot)):
            await asyncio.sleep(0.5)

    async def finish_gambling_round(self, message):
        if not self.bot.gamble_pacing.finish(self.cmd["id"], message.id):
            return False
        await discard(self.bot, self.cmd["id"])
        return True

    async def record_gambling_result(self, outcome, message=None):
        from utils.gamble_session import Streaks, save_state
        if not hasattr(self.bot, "_gamble_state_lock"):
            self.bot._gamble_state_lock = asyncio.Lock()
        async with self.bot._gamble_state_lock:
            if not hasattr(self.bot, "gamble_streaks"):
                self.bot.gamble_streaks = Streaks()
            self.bot.gamble_streaks.record(self.cmd["id"], outcome)
            if self.cmd["id"] == "coinflip" and message is not None:
                from utils.coinflip_probe import complete_result
                complete_result(self.bot, message.content, outcome)
                from utils.coinflip_history import chosen_side, get_history, save
                side = chosen_side(message.content)
                if get_history(self.bot).record(message.id, side, outcome) and getattr(self.bot, "_persist_gamble_streaks", False):
                    try:
                        await asyncio.to_thread(save, self.bot.user.id, message.id, side, outcome)
                    except (OSError, sqlite3.Error):
                        await self.bot.log("Không lưu được lịch sử Coinflip; dữ liệu phiên vẫn giữ trong bộ nhớ.")
            if getattr(self.bot, "_persist_gamble_streaks", False):
                try:
                    await asyncio.to_thread(save_state, self.bot.user.id, self.bot.gamble_streaks.snapshot())
                except (OSError, sqlite3.Error):
                    await self.bot.log("Không lưu được chuỗi thua; số liệu phiên vẫn giữ trong bộ nhớ.")

    def start_gambling(self, coroutine):
        self._gambling_alive = True
        self._gambling_task = asyncio.create_task(coroutine)

    async def stop_gambling(self):
        self._gambling_alive = False
        task = getattr(self, "_gambling_task", None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await discard(self.bot, self.cmd["id"])
