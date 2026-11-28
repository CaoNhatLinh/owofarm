import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import account_setup, bot_control
from website import website


class AccountSetupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        root = Path(self.folder.name)
        (root / "config").mkdir()
        for key, value in {"ROOT": root, "TOKENS_PATH": root / "tokens.txt",
                           "PENDING_PATH": root / "config" / "account_pending.json"}.items():
            change = patch.object(account_setup, key, value)
            change.start()
            self.addCleanup(change.stop)
        self.client = website.app.test_client()
        runtimes = patch("utils.bot_control.get_runtimes", return_value=[])
        self.runtimes = runtimes.start()
        self.addCleanup(runtimes.stop)
        self.data = {"token": "local_test_credential_" + "x" * 40, "channelId": "123456789012345678"}
        account_setup.changed.clear()
        self.addCleanup(account_setup.changed.clear)

    def test_local_save_read_and_replace_without_password(self):
        self.assertEqual(self.client.get("/api/account").json["token"], "")
        with patch("utils.bot_control.update_settings") as update:
            response = self.client.put("/api/account", json=self.data)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(response.json["token"], self.data["token"])
            self.assertTrue(response.json["restartRequired"])
            update.assert_not_called()
            replacement = {**self.data, "token": "replacement_" + "z" * 40}
            self.assertEqual(self.client.put("/api/account", json=replacement).status_code, 200)
            self.assertEqual(self.client.get("/api/account").json["token"], replacement["token"])
            self.assertEqual(account_setup.for_startup(), [[replacement["token"], self.data["channelId"]]])
            update.assert_called_once_with({"channelId": ""})
            self.assertFalse(account_setup.PENDING_PATH.exists())

    def test_remote_host_and_cross_origin_cannot_read_or_write_credentials(self):
        for options in ({"environ_overrides": {"REMOTE_ADDR": "192.0.2.1"}},
                        {"headers": {"Host": "external.example"}},
                        {"headers": {"Origin": "https://external.example"}}):
            self.assertEqual(self.client.get("/api/account", **options).status_code, 403)
            self.assertEqual(self.client.put("/api/account", json=self.data, **options).status_code, 403)
        self.assertFalse(account_setup.TOKENS_PATH.exists())

    def test_invalid_input_does_not_overwrite_or_echo_token(self):
        account_setup.save(self.data)
        before = account_setup.TOKENS_PATH.read_bytes()
        for data in ({**self.data, "channelId": "wrong"},
                     {**self.data, "token": "invalid token"}, {**self.data, "extra": True}):
            response = self.client.put("/api/account", json=data)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(self.data["token"], response.get_data(as_text=True))
            self.assertEqual(account_setup.TOKENS_PATH.read_bytes(), before)

    def test_multiple_accounts_are_preserved(self):
        account_setup.TOKENS_PATH.write_text("first 123\nsecond 456\n")
        response = self.client.get("/api/account")
        self.assertTrue(response.json["multiple"])
        self.assertEqual(response.json["token"], "")
        self.assertEqual(self.client.put("/api/account", json=self.data).status_code, 400)
        self.assertEqual(account_setup.TOKENS_PATH.read_text(), "first 123\nsecond 456\n")

    def connected_account(self):
        account_setup.TOKENS_PATH.write_text(f'{self.data["token"]} {self.data["channelId"]}\n')
        self.runtimes.return_value = [{"accountId": "test-connected"}]

    def test_same_token_switches_channel_live_and_persists_for_restart(self):
        self.connected_account()
        data = {**self.data, "channelId": "223456789012345678"}
        with patch("utils.bot_control.validate_channel") as check, patch("utils.bot_control.update_settings") as update:
            response = self.client.put("/api/account", json=data)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.json["channelApplied"])
            self.assertFalse(response.json["restartRequired"])
            check.assert_called_once_with(data["channelId"])
            update.assert_called_once_with({"channelId": data["channelId"]})
            self.assertEqual(account_setup.read_accounts(), [[data["token"], data["channelId"]]])

    def test_inaccessible_live_channel_leaves_previous_account_untouched(self):
        self.connected_account()
        before = account_setup.TOKENS_PATH.read_bytes()
        with patch("utils.bot_control.validate_channel", side_effect=ValueError("Không có quyền gửi")), patch("utils.bot_control.update_settings") as update:
            response = self.client.put("/api/account", json={**self.data, "channelId": "223456789012345678"})
            self.assertEqual(response.status_code, 400)
            self.assertEqual(account_setup.TOKENS_PATH.read_bytes(), before)
            self.assertFalse(account_setup.PENDING_PATH.exists())
            update.assert_not_called()

    def test_new_token_still_requires_restart_and_does_not_switch_old_account(self):
        self.connected_account()
        with patch("utils.bot_control.validate_channel") as check, patch("utils.bot_control.update_settings") as update:
            response = self.client.put("/api/account", json={**self.data, "token": "replacement_" + "z" * 40})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json["channelApplied"])
            self.assertTrue(response.json["restartRequired"])
            check.assert_not_called()
            update.assert_not_called()

    def test_failed_live_settings_write_reports_restart_instead_of_successful_switch(self):
        self.connected_account()
        with patch("utils.bot_control.validate_channel"), patch("utils.bot_control.update_settings", side_effect=OSError):
            response = self.client.put("/api/account", json={**self.data, "channelId": "223456789012345678"})
            self.assertEqual(response.status_code, 200)
            self.assertFalse(response.json["channelApplied"])
            self.assertTrue(response.json["restartRequired"])


class MultiAccountSetupTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        directory = Path(folder.name)
        (directory / "config").mkdir()
        self.patch_state(account_setup, "TOKENS_PATH", directory / "tokens.txt")
        self.patch_state(account_setup, "PENDING_PATH", directory / "config" / "account_pending.json")
        self.patch_state(account_setup, "_pending_accounts", set())
        self.patch_state(bot_control, "SETTINGS_PATH", directory / "config" / "dashboard.json")
        self.patch_state(bot_control, "_settings", dict(bot_control.DEFAULTS))
        self.patch_state(bot_control, "_account_settings", {})
        self.patch_state(bot_control, "_runtimes", {})
        self.addCleanup(account_setup.changed.clear)
        self.first_id = "111111111111111111"
        self.second_id = "222222222222222222"
        self.first_channel = "333333333333333333"
        self.second_channel = "444444444444444444"
        self.new_channel = "555555555555555555"
        self.first_token = self.token_for(self.first_id)
        self.second_token = self.token_for(self.second_id)

    def patch_state(self, module, name, value):
        change = patch.object(module, name, value)
        change.start()
        self.addCleanup(change.stop)

    @staticmethod
    def token_for(account_id, suffix="abcdefghij"):
        prefix = base64.b64encode(account_id.encode("ascii")).decode("ascii").rstrip("=")
        return f"{prefix}.fake.{suffix}"

    def add_account(self, token, channel):
        return account_setup.add({"token": token, "channelId": channel})

    def test_first_account_can_start_without_restart_but_replacing_token_cannot(self):
        first = self.add_account(self.first_token, self.first_channel)
        self.assertFalse(first["restartRequired"])
        self.assertEqual(account_setup.for_startup(), [[self.first_token, self.first_channel]])

        bot_control.publish_runtime("first", {"accountId": self.first_id, "connected": True})
        new_token = self.token_for(self.first_id, suffix="replacement")
        updated = account_setup.update_account(self.first_id, {"token": new_token})
        self.assertTrue(updated["restartRequired"])
        self.assertTrue(account_setup.list_accounts()[0]["restartRequired"])

    def test_add_lists_each_account_without_exposing_tokens_and_preserves_existing_channel(self):
        self.add_account(self.first_token, self.first_channel)
        bot_control.update_settings({"channelId": self.new_channel})
        result = self.add_account(self.second_token, self.second_channel)
        self.assertNotIn("token", result)
        self.assertTrue(result["restartRequired"])
        self.assertEqual(account_setup.read_accounts(), [[self.first_token, self.first_channel], [self.second_token, self.second_channel]])
        self.assertEqual(bot_control.get_settings()["channelId"], "")
        accounts = account_setup.list_accounts()
        self.assertEqual([row["accountId"] for row in accounts], [self.first_id, self.second_id])
        self.assertEqual([row["channelId"] for row in accounts], [self.new_channel, self.second_channel])
        self.assertTrue(all("token" not in row for row in accounts))
        self.assertNotIn("token", account_setup.read_account(self.second_id))
        self.assertEqual(account_setup.read_account(self.second_id, reveal=True)["token"], self.second_token)

    def test_changing_token_preserves_other_accounts_and_stable_identity(self):
        self.add_account(self.first_token, self.first_channel)
        self.add_account(self.second_token, self.second_channel)
        account_setup.for_startup()
        replacement = self.token_for(self.first_id, suffix="replacement")
        result = account_setup.update_account(self.first_id, {"token": replacement})
        self.assertEqual(result["accountId"], self.first_id)
        self.assertTrue(result["restartRequired"])
        self.assertNotIn("token", result)
        self.assertEqual(account_setup.read_accounts(), [[replacement, self.first_channel], [self.second_token, self.second_channel]])
        self.assertFalse(account_setup.list_accounts()[1]["restartRequired"])

    def test_duplicate_add_and_other_account_token_leave_file_intact(self):
        self.add_account(self.first_token, self.first_channel)
        self.add_account(self.second_token, self.second_channel)
        before = account_setup.TOKENS_PATH.read_bytes()
        with self.assertRaises(ValueError):
            self.add_account(self.token_for(self.first_id, suffix="replacement"), self.new_channel)
        with self.assertRaises(ValueError):
            account_setup.update_account(self.first_id, {"token": self.second_token})
        self.assertEqual(account_setup.TOKENS_PATH.read_bytes(), before)

    def test_live_channel_update_validates_only_the_selected_account(self):
        self.add_account(self.first_token, self.first_channel)
        self.add_account(self.second_token, self.second_channel)
        account_setup.for_startup()
        bot_control.publish_runtime("live", {"accountId": self.second_id, "name": "Acc 2"})
        with patch.object(bot_control, "validate_channel") as check:
            result = account_setup.update_account(self.second_id, {"channelId": self.new_channel})
        check.assert_called_once_with(self.new_channel, self.second_id)
        self.assertTrue(result["channelApplied"])
        self.assertFalse(result["restartRequired"])
        self.assertEqual(result["name"], "Acc 2")
        self.assertEqual(bot_control.get_settings(self.first_id)["channelId"], "")
        self.assertEqual(bot_control.get_settings(self.second_id)["channelId"], self.new_channel)
        self.assertEqual(account_setup.read_accounts()[1], [self.second_token, self.second_channel])

    def test_channel_errors_leave_saved_credentials_and_settings_intact(self):
        self.add_account(self.first_token, self.first_channel)
        account_setup.for_startup()
        bot_control.publish_runtime("live", {"accountId": self.first_id})
        before = account_setup.TOKENS_PATH.read_bytes()
        with patch.object(bot_control, "validate_channel", side_effect=ValueError("Không có quyền")):
            with self.assertRaises(ValueError):
                account_setup.update_account(self.first_id, {"channelId": self.new_channel})
        self.assertEqual(account_setup.TOKENS_PATH.read_bytes(), before)
        self.assertEqual(bot_control.get_settings(self.first_id)["channelId"], "")

    def test_offline_channel_edit_is_scoped_and_pending_until_startup(self):
        self.add_account(self.first_token, self.first_channel)
        account_setup.for_startup()
        with patch.object(bot_control, "validate_channel") as check:
            result = account_setup.update_account(self.first_id, {"channelId": self.new_channel})
        check.assert_not_called()
        self.assertFalse(result["channelApplied"])
        self.assertTrue(result["restartRequired"])
        self.assertEqual(result["channelId"], self.new_channel)
        account_setup.for_startup()
        self.assertFalse(account_setup.read_account(self.first_id)["restartRequired"])

    def test_account_api_only_returns_selected_token_with_explicit_local_reveal(self):
        client = website.app.test_client()
        for token, channel in [(self.first_token, self.first_channel), (self.second_token, self.second_channel)]:
            response = client.post("/api/accounts", json={"token": token, "channelId": channel})
            self.assertEqual(response.status_code, 201)
            self.assertNotIn("token", response.json["account"])

        selected = f"/api/accounts/{self.second_id}"
        listing = client.get("/api/accounts")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([row["accountId"] for row in listing.json["accounts"]], [self.first_id, self.second_id])
        self.assertNotIn(self.first_token, listing.get_data(as_text=True))
        self.assertNotIn(self.second_token, listing.get_data(as_text=True))
        self.assertNotIn("token", client.get(selected).json["account"])

        revealed = client.get(selected + "?reveal=1")
        self.assertEqual(revealed.status_code, 200)
        self.assertEqual(revealed.headers["Cache-Control"], "no-store")
        self.assertEqual(revealed.json["account"]["token"], self.second_token)
        self.assertNotIn(self.first_token, revealed.get_data(as_text=True))
        denied = client.get(selected + "?reveal=1", headers={"Origin": "https://external.example"})
        self.assertEqual(denied.status_code, 403)
        self.assertNotIn(self.second_token, denied.get_data(as_text=True))
