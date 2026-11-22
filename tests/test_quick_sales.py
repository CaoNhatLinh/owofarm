import asyncio
import unittest
from collections import OrderedDict
from contextlib import asynccontextmanager
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch

from utils import bot_control, quick_sale_jobs as jobs
from core.quick_sales import sell_weapons, sell_animals, run_sale, reader_for, SaleStopped
from website import website


class SalesApiTests(unittest.TestCase):
    def setUp(self):
        self.old_jobs=OrderedDict(jobs._jobs); self.old_handlers=dict(jobs._handlers)
        jobs._jobs.clear();jobs._handlers.clear()
        self.old_password=website.password;website.password="test"
        self.client=website.app.test_client();self.headers={"password":"test"}
        self.calls=[]
        async def handler(job): self.calls.append(job)
        jobs.register("42","Player",NS(),handler)
        self.handler=handler
        def dispatch(coroutine,loop):
            try:coroutine.send(None)
            except StopIteration:pass
            finally:coroutine.close()
        self.dispatch=patch("utils.quick_sale_jobs.asyncio.run_coroutine_threadsafe",side_effect=dispatch)
        self.dispatch.start();bot_control.set_running(True)

    def tearDown(self):
        self.dispatch.stop();jobs._jobs.clear();jobs._jobs.update(self.old_jobs)
        jobs._handlers.clear();jobs._handlers.update(self.old_handlers)
        website.password=self.old_password;bot_control.set_running(True)

    def request(self,**values):
        data=dict(kind="weapons",maxRarity="uncommon",accountId="42",requestId="request-0001")
        data.update(values)
        return self.client.post("/api/sales",json=data,headers=self.headers)

    def test_authentication_and_buttons(self):
        self.assertEqual(self.client.get("/api/sales", environ_overrides={"REMOTE_ADDR":"192.0.2.1"}).status_code,403)
        self.assertEqual(self.client.post("/api/sales",json={}, environ_overrides={"REMOTE_ADDR":"192.0.2.1"}).status_code,403)
        html=self.client.get("/").data
        self.assertIn(b'id="sell-weapons"',html);self.assertIn(b'id="sell-animals"',html)
        self.assertIn(b'id="sacrifice-animals"',html)

    def test_duplicate_request_is_not_submitted_twice(self):
        first=self.request(); second=self.request()
        self.assertEqual(first.status_code,202);self.assertEqual(second.status_code,202)
        self.assertEqual(len(self.calls),1)
        self.assertEqual(first.json["job"]["id"],second.json["job"]["id"])
        self.assertEqual(self.request(maxRarity="rare").status_code,400)

    def test_account_is_scoped_and_concurrent_same_account_is_blocked(self):
        self.request()
        self.assertEqual(self.request(requestId="request-0002").status_code,409)
        jobs.register("43","Other",NS(),self.handler)
        self.assertEqual(self.request(accountId="43",requestId="request-0003").status_code,202)
        self.assertEqual([item["accountId"] for item in self.calls],["42","43"])

    def test_invalid_requests_are_rejected_but_manual_pause_is_allowed(self):
        for data in [dict(kind="all"),dict(maxRarity="gem"),dict(maxRarity=[]),dict(kind=[]),dict(requestId="bad")]:
            self.assertEqual(self.request(**data).status_code,400)
        self.assertEqual(self.request(accountId="unknown").status_code,409)
        bot_control.set_running(False)
        self.assertEqual(self.request().status_code,202)
        self.assertEqual(len(self.calls),1)
        self.assertFalse(bot_control.is_running())

    def test_completed_jobs_allow_a_new_explicit_sale(self):
        self.request();jobs.update("request-0001",state="success",sold=3,message="Đã bán 3 vũ khí.")
        self.assertEqual(self.request(requestId="request-0002").status_code,202)
        data=self.client.get("/api/sales",headers=self.headers)
        self.assertEqual(data.json["jobs"][0]["sold"],3)
        self.assertEqual(data.headers["Cache-Control"],"no-store")

    def test_rank_cutoffs_are_explicit_and_differ_by_inventory(self):
        self.assertEqual(jobs.ranks_through("weapons","rare"),["common","uncommon","rare"])
        self.assertEqual(jobs.ranks_through("animals","gem"),["common","uncommon","rare","epic","patreon","special","mythical","gem"])
        self.assertEqual(jobs.ranks_through("sacrifice","rare"),["common","uncommon","rare"])

    def test_sacrifice_has_its_own_action_and_shares_account_lock(self):
        self.assertEqual(self.request(kind="sacrifice",maxRarity="rare").status_code,202)
        self.assertEqual(self.calls[0]["kind"],"sacrifice")
        self.assertEqual(self.request(requestId="request-0002").status_code,409)

    def test_sacrifice_is_allowed_while_farm_stays_stopped(self):
        bot_control.set_running(False)
        self.assertEqual(self.request(kind="sacrifice").status_code,202)
        self.assertEqual(self.calls[0]["kind"],"sacrifice")
        self.assertFalse(bot_control.is_running())


def fake_bot():
    return NS(cm=NS(id=99),settings_dict=NS(prefix="o"),
        ch=NS(command_handler_status=NS(captcha=False,sleep=False)),
        response_guard=NS(cooling_down=False,wait_ready=AsyncMock()),
        get_cog=lambda _:None,log=AsyncMock(),wait_until_ready=AsyncMock())


def rank_response(count=1):
    return (None,"Player, You sold all your Common weapons for **100** cowoncy!\n**| Sold:** "+"<:cbow:123>"*count)


class SaleExecutionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        bot_control.set_running(True)
        self.bot=fake_bot();self.context=(99,"o")
        self.job=dict(id="execution-001",accountId="42",kind="weapons",maxRarity="rare",sold=0,state="queued")
        self.old_jobs=OrderedDict(jobs._jobs);jobs._jobs[self.job["id"]]=dict(self.job)

    async def asyncTearDown(self):
        jobs._jobs.clear();jobs._jobs.update(self.old_jobs);bot_control.set_running(True)

    async def test_weapon_sale_uses_rank_commands_without_reading_inventory(self):
        reader=NS(_full_inventory=AsyncMock(side_effect=AssertionError("Must not read inventory")),
            _request_response=AsyncMock(side_effect=[rank_response(2),(None,"You do not have any weapons with this rank!"),rank_response(1)]))
        self.assertEqual(await sell_weapons(self.bot,reader,self.job,self.context),3)
        self.assertEqual([call.args for call in reader._request_response.await_args_list],
            [("weapon_rank_sell","sell","cw"),("weapon_rank_sell","sell","uw"),("weapon_rank_sell","sell","rw")])
        reader._full_inventory.assert_not_awaited()

    async def test_empty_ranks_are_skipped_without_retry(self):
        reader=NS(_request_response=AsyncMock(return_value=(None,"Player, you do not have any weapons with this rank!")))
        self.assertEqual(await sell_weapons(self.bot,reader,self.job,self.context),0)
        self.assertEqual(reader._request_response.await_count,3)

    async def test_missing_confirmation_stops_without_retry(self):
        reader=NS(_request_response=AsyncMock(return_value=None))
        with self.assertRaises(SaleStopped):await sell_weapons(self.bot,reader,self.job,self.context)
        self.assertEqual(reader._request_response.await_count,1)

    async def test_unexpected_reply_does_not_confirm_bulk_sale(self):
        reader=NS(_request_response=AsyncMock(return_value=(None,"You sold a(n) Common Bow")))
        with self.assertRaises(SaleStopped):await sell_weapons(self.bot,reader,self.job,self.context)
        self.assertEqual(reader._request_response.await_count,1)

    async def test_manual_pause_allows_sale_but_new_captcha_blocks_it(self):
        reader=NS(_request_response=AsyncMock(return_value=(None,"You do not have any weapons with this rank!")))
        bot_control.set_running(False)
        self.assertEqual(await sell_weapons(self.bot,reader,self.job,self.context),0)
        self.assertFalse(bot_control.is_running())
        reader._request_response.reset_mock()
        self.bot.ch.command_handler_status.captcha=True
        with self.assertRaises(SaleStopped):await sell_weapons(self.bot,reader,self.job,self.context)
        reader._request_response.assert_not_awaited()

    async def test_channel_change_stops_remaining_rank_commands(self):
        async def changed(*args):
            self.bot.cm.id=100
            return rank_response(2)
        reader=NS(_request_response=AsyncMock(side_effect=changed))
        with self.assertRaises(SaleStopped):await sell_weapons(self.bot,reader,self.job,self.context)
        self.assertEqual(reader._request_response.await_count,1)

    async def test_animal_sale_sends_only_ranks_at_or_below_cutoff(self):
        self.job.update(kind="animals",maxRarity="uncommon")
        reader=NS(_request_response=AsyncMock(return_value=(None,"Playerfox123 sold **<:common:1>x2 <:uncommon:2>x3** for a total of **100 cowoncy**")))
        self.assertEqual(await sell_animals(self.bot,reader,self.job,self.context),5)
        reader._request_response.assert_awaited_once_with("animal_sell","sell","c u")

    async def test_no_animals_and_missing_response_are_handled_without_retry(self):
        self.job.update(kind="animals",maxRarity="rare")
        reader=NS(_request_response=AsyncMock(return_value=(None,"Player, You don't have enough animals! >:c")))
        self.assertEqual(await sell_animals(self.bot,reader,self.job,self.context),0)
        reader._request_response=AsyncMock(return_value=None)
        with self.assertRaises(SaleStopped):await sell_animals(self.bot,reader,self.job,self.context)
        self.assertEqual(reader._request_response.await_count,1)

    async def test_sacrifice_sends_sac_and_updates_only_sacrifice_timer(self):
        self.job.update(kind="sacrifice",maxRarity="rare")
        seller=NS(sell_lastran=123,sac_lastran=0)
        self.bot.get_cog=lambda _:seller
        reader=NS(_request_response=AsyncMock(return_value=(None,"Player sacrificed **<:rare:1>x5** for a total of **<a:essence:2> 100**")))
        self.assertEqual(await sell_animals(self.bot,reader,self.job,self.context),5)
        reader._request_response.assert_awaited_once_with("animal_sacrifice","sac","c u r")
        self.assertEqual(seller.sell_lastran,123)
        self.assertGreater(seller.sac_lastran,0)

    async def test_sacrifice_does_not_accept_a_sale_confirmation(self):
        self.job.update(kind="sacrifice",maxRarity="rare")
        reader=NS(_request_response=AsyncMock(return_value=(None,"Player sold **<:rare:1>x5** for a total of **100 cowoncy**")))
        with self.assertRaises(SaleStopped):await sell_animals(self.bot,reader,self.job,self.context)
        self.assertEqual(reader._request_response.await_count,1)

    async def test_partial_job_reports_only_confirmed_sales(self):
        reader=NS(_request_response=AsyncMock(side_effect=[rank_response(2),None]))
        @asynccontextmanager
        async def use_reader(_):yield reader
        with patch("core.quick_sales.reader_for",use_reader):await run_sale(self.bot,self.job)
        status=next(job for job in jobs.jobs() if job["id"]==self.job["id"])
        self.assertEqual(status["state"],"partial");self.assertEqual(status["sold"],2)
        self.assertEqual(reader._request_response.await_count,2)

    async def test_sales_reader_works_without_auto_equipment_cog(self):
        from test_weapons_runtime import make_bot
        bot=make_bot();bot.get_cog=lambda _:None;bot.add_listener=Mock();bot.remove_listener=Mock()
        async with reader_for(bot) as reader:
            self.assertIsNone(reader._task)
            self.assertEqual(len(bot.message_dispatcher._message_handlers),1)
        self.assertEqual(len(bot.message_dispatcher._message_handlers),0)
        self.assertEqual(bot.remove_listener.call_count,2)


if __name__ == "__main__":unittest.main()
