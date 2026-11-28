import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from utils import runtime_handler as runtime
from website import website


class WeeklyRuntimeTests(unittest.TestCase):
    def test_legacy_only_imports_intervals_from_the_current_week(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "weekly.json"
            path.write_text(json.dumps({
                "0": [datetime(2026, 11, 16, 9).timestamp(), datetime(2026, 11, 16, 10).timestamp()],
                "1": [datetime(2026, 11, 24, 9).timestamp(), datetime(2026, 11, 24, 10).timestamp()],
            }), encoding="utf-8")
            result = runtime.load_weekly_runtime(path, now=datetime(2026, 11, 24, 12))
        self.assertEqual(result, {"week": "2026-11-23", "seconds": [0, 3600, 0, 0, 0, 0, 0]})

    def test_midnight_splits_sample_and_monday_starts_a_new_week(self):
        start = datetime(2026, 11, 24)
        current = runtime.accumulate_runtime(runtime.weekly_totals(start), start, 10)
        self.assertEqual(current["seconds"], [10, 0, 0, 0, 0, 0, 0])
        next_week = runtime.accumulate_runtime(current, datetime(2026, 11, 30, 0, 0, 2), 10)
        self.assertEqual(next_week, {"week": "2026-11-30", "seconds": [2, 0, 0, 0, 0, 0, 0]})

    def test_api_keeps_weekly_seconds_separate_from_this_launch(self):
        with (patch.object(website, "load_weekly_runtime", return_value={"seconds": [0, 7200, 0, 0, 0, 0, 0]}),
              patch.object(runtime, "_session_started", 100),
              patch.object(runtime.time, "monotonic", return_value=108)):
            response = website.app.test_client().get("/api/fetch_weekly_runtime").json
        self.assertEqual(response["runtime_data"], [0, 120, 0, 0, 0, 0, 0])
        self.assertEqual(response["current_uptime"], [0, 8])
