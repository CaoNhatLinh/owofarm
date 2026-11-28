import unittest
from threading import Event
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

from utils import bot_control
from utils.gambling_control import (
    WALLET_CHECK_INTERVAL,
    balance_blocks,
    command_allowed,
    confirm_wallet,
    invalidate_wallet,
    request_wallet_check,
    wallet_waiting,
)
from utils.response_guard import ResponseGuard


OWO = 408
CHANNEL = 99
PLAYER = 42
FUNDS_ERROR = "**Nu! <@42>**, you don't have enough cowoncy!"


def reply(content=FUNDS_ERROR, *, author=OWO, channel=CHANNEL, message_id=200, reference_id=None):
    reference = NS(message_id=reference_id) if reference_id is not None else None
    return NS(content=content, author=NS(id=author), channel=NS(id=channel), id=message_id,
              reference=reference, embeds=[], components=[])


class GambleWalletTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config = {**bot_control.DEFAULTS, "coinflipEnabled": True, "slotsEnabled": True, "blackjackEnabled": True}
        running = Event()
        running.set()
        self.enterContext(patch.multiple(bot_control, _settings=self.config, _account_settings={},
                                         _runtimes={}, _running=running, _paused_accounts=set()))

    def make_bot(self, name="wallet"):
        bot = NS(response_guard=ResponseGuard(name, channel_id=CHANNEL),
                 stats=NS(balance=32_000, has_updated_balance=True))
        self.confirm(bot, 80, 32_000)
        return bot

    def observe(self, bot, response):
        return bot.response_guard.observe(response, PLAYER, {"Player"}, OWO)

    def record_request(self, bot, command):
        guard = bot.response_guard
        guard.expect(CHANNEL, min_id=100, command=command)
        guard.sent(NS(id=100, channel=NS(id=CHANNEL)), command=command)

    def confirm(self, bot, message_id, balance):
        accepted = confirm_wallet(bot, message_id, balance)
        if accepted:
            bot.stats.has_updated_balance = True
            bot.stats.balance = balance
        return accepted

    def test_rejection_blocks_all_bets_until_a_new_sufficient_balance(self):
        bot = self.make_bot()
        other = self.make_bot("other-wallet")
        self.assertTrue(self.confirm(bot, 90, 32_000))
        self.assertFalse(balance_blocks(bot, 8_000))

        invalidate_wallet(bot, 200)
        bot.stats.balance += 10_000
        self.assertTrue(wallet_waiting(bot))
        self.assertTrue(balance_blocks(bot, 8_000))
        self.assertFalse(balance_blocks(other, 8_000))
        for wager in ("ocf 8000 heads", "oslots 8000", "obj 8000"):
            self.assertFalse(command_allowed(wager, "o", {}, bot))
            self.assertTrue(command_allowed(wager, "o", {}, other))
        for farm_command in ("oh", "ob", "osell c", "ocash"):
            self.assertTrue(command_allowed(farm_command, "o", {}, bot))

        self.assertFalse(self.confirm(bot, 199, 50_000))
        self.assertTrue(balance_blocks(bot, 8_000))
        self.assertTrue(self.confirm(bot, 201, 3_141))
        self.assertTrue(balance_blocks(bot, 8_000))
        self.assertTrue(self.confirm(bot, 202, 8_000))
        self.assertFalse(balance_blocks(bot, 8_000))
        self.assertTrue(command_allowed("obj 8000", "o", {}, bot))

    def test_own_game_rejection_is_observed_with_or_without_reply_reference(self):
        for game in ("coinflip", "slots", "blackjack"):
            with self.subTest(game=game):
                bot = self.make_bot()
                self.record_request(bot, game)
                response = reply("You don't have enough cowoncy!", reference_id=100) if game == "blackjack" else reply()
                self.assertTrue(self.observe(bot, response))
                self.assertTrue(wallet_waiting(bot))
                self.assertTrue(balance_blocks(bot, 8_000))

    def test_unrelated_rejections_do_not_invalidate_the_wallet(self):
        cases = (
            ("blackjack", reply(author=777)),
            ("blackjack", reply(channel=123)),
            ("blackjack", reply("<@777>, you don't have enough cowoncy!")),
            ("blackjack", reply(reference_id=101)),
            ("blackjack", reply(message_id=90)),
            ("hunt", reply()),
        )
        for command, response in cases:
            with self.subTest(command=command, response=response):
                bot = self.make_bot()
                self.record_request(bot, command)
                self.observe(bot, response)
                self.assertFalse(wallet_waiting(bot))
                self.assertFalse(balance_blocks(bot, 8_000))

    def test_early_unreferenced_rejection_is_applied_after_the_send_is_recorded(self):
        for rest_enabled in (False, True):
            with self.subTest(rest_enabled=rest_enabled):
                self.config["restEnabled"] = rest_enabled
                bot = self.make_bot()
                guard = bot.response_guard
                guard.expect(CHANNEL, min_id=100, command="blackjack")
                self.observe(bot, reply())
                self.assertFalse(wallet_waiting(bot))
                guard.sent(NS(id=100, channel=NS(id=CHANNEL)), command="blackjack")
                self.assertTrue(wallet_waiting(bot))

    def test_unaffordable_next_wager_only_blocks_its_game_until_a_balance_check(self):
        bot = self.make_bot()
        self.assertTrue(self.confirm(bot, 90, 3_141))
        self.assertTrue(balance_blocks(bot, 8_000, "blackjack"))
        self.assertFalse(balance_blocks(bot, 200, "slots"))
        bot.stats.balance += 10_000
        self.assertTrue(balance_blocks(bot, 8_000, "blackjack"))
        self.assertTrue(self.confirm(bot, 91, 8_000))
        self.assertFalse(balance_blocks(bot, 8_000, "blackjack"))

    async def test_unknown_balance_only_queues_one_cash_check_per_interval(self):
        bot = self.make_bot()
        bot.response_guard = ResponseGuard("fresh-wallet", channel_id=CHANNEL)
        bot.stats.has_updated_balance = False
        bot.cm = NS(id=CHANNEL)
        bot.alias = {}
        bot.ch = NS(should_not_send=False, cmds_state={"cash": {"in_queue": False}},
                    put_queue=AsyncMock(return_value=True))
        self.assertTrue(balance_blocks(bot, 200, "blackjack"))
        self.assertFalse(command_allowed("obj 200", "o", {}, bot))

        now = 100.0
        with patch("utils.gambling_control.time", NS(monotonic=lambda: now)):
            await request_wallet_check(bot)
            await request_wallet_check(bot)
            bot.ch.put_queue.assert_awaited_once_with(
                {"cmd_name": "cash", "prefix": True, "checks": False, "id": "cash"}, wait=False)
            now += WALLET_CHECK_INTERVAL
            bot.ch.cmds_state["cash"]["in_queue"] = True
            await request_wallet_check(bot)
            self.assertEqual(bot.ch.put_queue.await_count, 1)
            bot.ch.cmds_state["cash"]["in_queue"] = False
            await request_wallet_check(bot)
            self.assertEqual(bot.ch.put_queue.await_count, 2)
            now += WALLET_CHECK_INTERVAL
            self.config.update(coinflipEnabled=False, slotsEnabled=False, blackjackEnabled=False)
            await request_wallet_check(bot)
            self.assertEqual(bot.ch.put_queue.await_count, 2)
