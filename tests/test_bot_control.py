import asyncio
import unittest

from core.command_handler import CommandHandler, CommandHandlerStatus
from utils import bot_control
from website import website


class WebControlTests(unittest.TestCase):
    def setUp(self):
        self.previous_password = website.password
        website.password = "test-password"
        self.client = website.app.test_client()
        self.headers = {"password": "test-password"}
        bot_control.set_running(True)

    def tearDown(self):
        website.password = self.previous_password
        bot_control.set_running(True)

    def test_controls_are_present_in_dashboard(self):
        response = self.client.get("/")
        self.assertIn(b'id="bot-toggle"', response.data)
        self.assertIn(b'id="bot-status"', response.data)

    def test_remote_read_and_write_are_rejected(self):
        self.assertEqual(self.client.get("/api/bot", environ_overrides={"REMOTE_ADDR":"192.0.2.1"}).status_code,403)
        self.assertEqual(self.client.post("/api/bot", json={"action": "stop"}, headers={"password": "wrong"}, environ_overrides={"REMOTE_ADDR":"192.0.2.1"}).status_code,403)
        self.assertTrue(bot_control.is_running())

    def test_stop_start_are_idempotent_and_state_is_not_cached(self):
        for action, expected in [("stop", False), ("stop", False), ("start", True), ("start", True)]:
            response = self.client.post("/api/bot", json={"action": action}, headers=self.headers)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["running"], expected)
            state = self.client.get("/api/bot", headers=self.headers)
            self.assertEqual(state.json["running"], expected)
            self.assertEqual(state.headers["Cache-Control"], "no-store")

    def test_malformed_requests_do_not_change_state(self):
        for data in [None, [], {"action": "toggle"}, {"running": False}]:
            response = self.client.post("/api/bot", json=data, headers=self.headers)
            self.assertEqual(response.status_code, 400)
            self.assertTrue(bot_control.is_running())

    def test_pause_blocks_normal_and_priority_commands(self):
        handler = CommandHandler.__new__(CommandHandler)
        handler.command_handler_status = CommandHandlerStatus()
        self.assertFalse(handler.should_not_send)
        bot_control.set_running(False)
        self.assertTrue(handler.should_not_send)
        self.assertFalse(handler.can_send_if_priority)

    def test_start_requests_resume_for_registered_clients(self):
        generation = bot_control.get_resume_generation()
        handler = CommandHandler.__new__(CommandHandler)
        handler.command_handler_status = CommandHandlerStatus()
        handler.command_handler_status.captcha = True
        handler.command_handler_status.sleep = True
        self.client.post("/api/bot", json={"action": "stop"}, headers=self.headers)
        self.client.post("/api/bot", json={"action": "start"}, headers=self.headers)
        self.assertGreater(bot_control.get_resume_generation(), generation)
        self.assertTrue(handler.command_handler_status.captcha)
        self.assertTrue(handler.command_handler_status.sleep)
        self.assertTrue(handler.should_not_send)
        self.assertFalse(handler.can_send_if_priority)


class PauseWaitTests(unittest.IsolatedAsyncioTestCase):
    async def test_wait_yields_to_loop_and_resumes(self):
        bot_control.set_running(False)
        try:
            waiter = asyncio.create_task(bot_control.wait_until_running())
            await asyncio.sleep(.01)
            self.assertFalse(waiter.done())
            bot_control.set_running(True)
            await asyncio.wait_for(waiter, 1)
        finally:
            bot_control.set_running(True)


if __name__ == "__main__":
    unittest.main()
