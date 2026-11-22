import unittest
from html.parser import HTMLParser
from collections import Counter
from website import website


class Layout(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.stack=[]; self.ids=[]; self.areas={}; self.tabs={}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs=dict(attrs)
        area=attrs.get("id") if attrs.get("role")=="tabpanel" and attrs.get("id", "").startswith("page-") else (self.stack[-1][1] if self.stack else None)
        if "id" in attrs:
            self.ids.append(attrs["id"]);self.areas[attrs["id"]]=area
        if "data-page" in attrs:
            self.tabs[attrs["data-page"]]=attrs
        if tag not in {"input","meta","link","br","hr","img"}:
            self.stack.append((tag,area))

    def handle_endtag(self,tag):
        if self.stack and self.stack[-1][0]==tag:self.stack.pop()


class DashboardLayoutTests(unittest.TestCase):
    def test_tabs_cover_existing_features_without_duplicate_controls(self):
        layout=Layout(website.app.test_client().get("/").data.decode())
        self.assertEqual(set(layout.tabs),{"overview","controls","gambling","simulation","inventory","collection","activity"})
        self.assertTrue(all(count==1 for count in Counter(layout.ids).values()))
        expected={"overview":["bot-status","cowoncy_earnings","weekly_runtimes","total_commands"],
                  "controls":["rest-enabled","message-interval","owo-enabled","hunt-enabled","battle-enabled","gem-order","channel-id","command-prefix"],
                  "gambling":["coinflip-bet","coinflip-side","coinflip-switch-start","coinflip-probe-target","coinflip-history-window","coinflip-frequency-heads","coinflip-frequency-tails","coinflip-recent-frequency-heads","coinflip-recent-frequency-tails","slots-enabled","blackjack-double","gamble_earnings"],
                  "inventory":["sell-weapons","sell-animals","sacrifice-animals"],
                  "simulation":["sim-run","sim-base","sim-chart","sim-rows","sim-fill"],
                  "collection":["catch-total","catch-groups"],"activity":["messages","log-filter"]}
        for page,controls in expected.items():
            for control in controls:
                self.assertEqual(layout.areas[control],"page-"+page,control)
        for page,attrs in layout.tabs.items():
            self.assertEqual(attrs["aria-controls"],"page-"+page)
        self.assertIsNone(layout.areas["bot-toggle"])
        self.assertIsNone(layout.areas["save-settings"])
