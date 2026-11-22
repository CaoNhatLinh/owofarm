import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import account_setup
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
