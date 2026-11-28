import unittest
from contextlib import ExitStack
from html.parser import HTMLParser
from collections import Counter, deque
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from utils import account_setup, bot_control
from website import website


class Layout(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.stack=[]; self.ids=[]; self.areas={}; self.tabs={}
        self.assets = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        area=attrs.get("id") if attrs.get("role")=="tabpanel" and attrs.get("id", "").startswith("page-") else (self.stack[-1][1] if self.stack else None)
        if "id" in attrs:
            self.ids.append(attrs["id"]);self.areas[attrs["id"]]=area
        if "data-page" in attrs:
            self.tabs[attrs["data-page"]]=attrs
        if tag == "script" and "src" in attrs:
            self.assets.append(attrs["src"])
        if tag == "link" and attrs.get("rel") == "stylesheet" and attrs.get("media") != "print":
            self.assets.append(attrs["href"])
        if tag not in {"input","meta","link","br","hr","img"}:
            self.stack.append((tag,area))

    def handle_endtag(self,tag):
        if self.stack and self.stack[-1][0]==tag:self.stack.pop()


class DashboardLayoutTests(unittest.TestCase):
    static_assets = (
        "style.css",
        "vendor/chart.js/chart.umd.js",
        "gamble_math.js",
        "script.js",
        "simulation.js",
        "account_setup.js",
    )

    def test_dashboard_loads_versioned_local_assets(self):
        client = website.app.test_client()
        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertTrue(page.cache_control.no_store)

        assets = Layout(page.get_data(as_text=True)).assets
        self.assertCountEqual([urlsplit(asset).path for asset in assets],
                              [f"/static/{name}" for name in self.static_assets])
        for asset in assets:
            with self.subTest(asset=asset):
                url = urlsplit(asset)
                self.assertFalse(url.scheme or url.netloc)
                self.assertTrue(parse_qs(url.query).get("v"))
                self.assertEqual(client.get(asset, buffered=True).status_code, 200)

    def test_console_keeps_recent_entries_and_serves_them_as_plain_text(self):
        with patch.object(website, "website_logs", deque(maxlen=website.website_logs.maxlen)):
            for index in range(305):
                website.website_append(f"<div>Entry {index}</div>")
            response = website.app.test_client().get("/api/console")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "text/plain")
        self.assertTrue(response.cache_control.no_store)
        lines = response.get_data(as_text=True).splitlines()
        self.assertEqual(len(lines), 300)
        self.assertEqual((lines[0], lines[-1]), ("<div>Entry 5</div>", "<div>Entry 304</div>"))

    def test_asset_version_changes_when_file_content_changes(self):
        client = website.app.test_client()

        def stylesheet_url():
            assets = Layout(client.get("/").get_data(as_text=True)).assets
            return next(asset for asset in assets if urlsplit(asset).path == "/static/style.css")

        with TemporaryDirectory() as folder, patch.object(website.app, "_static_folder", folder):
            for name in self.static_assets:
                path = Path(folder) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"first version")
            previous_url = stylesheet_url()
            (Path(folder) / "style.css").write_bytes(b"newer version")
            self.assertNotEqual(stylesheet_url(), previous_url)

    def test_tabs_cover_existing_features_without_duplicate_controls(self):
        layout=Layout(website.app.test_client().get("/").data.decode())
        self.assertEqual(set(layout.tabs),{"overview","controls","gambling","simulation","inventory","collection","activity","accounts"})
        self.assertTrue(all(count==1 for count in Counter(layout.ids).values()))
        expected={"overview":["bot-status","cowoncy_earnings","weekly_runtimes","total_commands"],
                  "controls":["rest-enabled","message-interval","owo-enabled","hunt-enabled","battle-enabled","random-chat-enabled","gems-enabled","gem-order","gem-skip-rarity","channel-id","command-prefix"],
                  "gambling":["coinflip-bet","coinflip-side","coinflip-switch-start","coinflip-probe-target","coinflip-history-window","coinflip-frequency-heads","coinflip-frequency-tails","coinflip-recent-frequency-heads","coinflip-recent-frequency-tails","slots-enabled","blackjack-double","gamble_earnings"],
                  "inventory":["sell-weapons","sell-animals","sacrifice-animals","hunt-emergency-sell-enabled","zoo-sacrifice-surplus-enabled"],
                  "simulation":["sim-run","sim-base","sim-chart","sim-rows","sim-fill","sim-account-name"],
                  "accounts":["account-list","account-add","account-token","account-save"],
                  "collection":["catch-total","catch-groups"],"activity":["messages","log-filter"]}
        for page,controls in expected.items():
            for control in controls:
                self.assertEqual(layout.areas[control],"page-"+page,control)
        for page,attrs in layout.tabs.items():
            self.assertEqual(attrs["aria-controls"],"page-"+page)
        self.assertIsNone(layout.areas["bot-toggle"])
        self.assertIsNone(layout.areas["account-scope"])
        self.assertEqual(layout.areas["team-setup-enabled"], "page-controls")
        self.assertEqual(layout.areas["huntbot-max"], "page-controls")
        self.assertIsNone(layout.areas["save-settings"])


class CowoncyDashboardApiTests(unittest.TestCase):
    def test_datasets_label_accounts_by_name_and_keep_hourly_values(self):
        first = "100000000000000001"
        second = "100000000000000002"
        unknown = "100000000000000003"
        earnings = [
            {"user_id": first, "hour": 0, "earnings": 120},
            {"user_id": unknown, "hour": 0, "earnings": 540},
            {"user_id": int(second), "hour": 1, "earnings": -500},
            {"user_id": first, "hour": 23, "earnings": 1000},
        ]
        totals = [{"cowoncy": 2000, "captchas": 2}, {"cowoncy": 800, "captchas": 1}]
        with (
            patch.object(website, "get_from_db", side_effect=[earnings, totals]),
            patch.object(account_setup, "list_accounts", return_value=[{
                "accountId": first, "name": "Linh Nguyễn",
            }]),
            patch.object(bot_control, "get_runtimes", return_value=[{
                "accountId": second, "name": "Nhã Phương",
            }]),
        ):
            response = website.app.test_client().get("/api/fetch_cowoncy_data")

        self.assertEqual(response.status_code, 200)
        result = response.get_json()
        self.assertEqual(result["total_cash"], 2800)
        self.assertEqual(result["total_captchas"], 3)
        self.assertEqual(len(result["data"]["labels"]), 24)
        datasets = {series["accountId"]: series for series in result["data"]["datasets"]}
        self.assertEqual(set(datasets), {first, second, unknown})
        self.assertEqual(datasets[first]["label"], "Linh Nguyễn")
        self.assertEqual(datasets[second]["label"], "Nhã Phương")
        self.assertTrue(datasets[unknown]["label"].startswith("Tài khoản "))
        self.assertNotIn(unknown, datasets[unknown]["label"])
        self.assertEqual(datasets[first]["data"], [120] + [0] * 22 + [1000])
        self.assertEqual(datasets[second]["data"], [0, -500] + [0] * 22)
        self.assertEqual(datasets[unknown]["data"], [540] + [0] * 23)


class AccountDashboardApiTests(unittest.TestCase):
    first = "100000000000000001"
    second = "100000000000000002"

    def setUp(self):
        resources = self.enterContext(ExitStack())
        folder = resources.enter_context(TemporaryDirectory())
        for key, value in {
            "SETTINGS_PATH": Path(folder) / "dashboard.json", "_settings": dict(bot_control.DEFAULTS),
            "_account_settings": {}, "_runtimes": {}, "_paused_accounts": set(),
            "_running": Event(), "_resume_generation": 0, "_account_resume_generations": {},
        }.items():
            resources.enter_context(patch.object(bot_control, key, value))
        resources.enter_context(patch.object(account_setup, "list_accounts", return_value=[
            {"accountId": self.first}, {"accountId": self.second},
        ]))
        bot_control.set_running(True)
        self.client = website.app.test_client()

    def test_saving_one_account_does_not_change_the_other_or_shared_defaults(self):
        first_url = f"/api/settings?accountId={self.first}"
        second_url = f"/api/settings?accountId={self.second}"
        initial = self.client.get("/api/settings").json["settings"]
        channel = "100000000000000003"
        overrides = {"coinflipBet": 550, "huntEnabled": False, "gemSkipAtOrAbove": "mythical", "channelId": channel,
                     "teamSetupEnabled": True, "huntbotEnabled": True, "zooSacrificeSurplusEnabled": True}
        result = self.client.patch(first_url, json=overrides)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["overrides"], overrides)
        self.assertEqual(self.client.get(second_url).json["settings"], initial)
        self.client.patch("/api/settings", json={"coinflipBet": 700})
        self.assertEqual(self.client.get(first_url).json["settings"]["coinflipBet"], 550)
        self.assertEqual(self.client.get(second_url).json["settings"]["coinflipBet"], 700)
        reset = self.client.delete(first_url).json
        self.assertEqual(reset["settings"]["coinflipBet"], 700)
        self.assertEqual(reset["overrides"], {"channelId": channel})

    def test_change_channel_validates_only_authenticated_selected_account(self):
        channel = "100000000000000003"
        with patch.object(bot_control, "has_channel_checker", side_effect=lambda account: account == self.first), \
                patch.object(bot_control, "validate_channel") as check:
            for account in (self.first, self.second):
                response = self.client.patch(f"/api/settings?accountId={account}", json={"channelId": channel})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json["settings"]["channelId"], channel)
            check.assert_called_once_with(channel, self.first)

    def test_account_pause_is_separate_from_master_pause(self):
        first_url = f"/api/bot?accountId={self.first}"
        second_url = f"/api/bot?accountId={self.second}"
        stopped = self.client.post(first_url, json={"action": "stop"}).json
        self.assertFalse(stopped["running"])
        self.assertTrue(stopped["allRunning"])
        self.assertTrue(self.client.get(second_url).json["running"])
        self.client.post("/api/bot", json={"action": "stop"})
        self.assertFalse(self.client.get(second_url).json["running"])
        self.client.post("/api/bot", json={"action": "start"})
        self.assertFalse(self.client.get(first_url).json["running"])
        self.assertTrue(self.client.get(second_url).json["running"])
