import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import patch


class ChartWorker:
    def __init__(self, connection):
        self.connection = connection

    def update_database(self, sql, params):
        with self.connection:
            self.connection.execute(sql, params)

    async def update_database_async(self, sql, params):
        self.update_database(sql, params)

    async def get_from_db(self, sql, params):
        return self.connection.execute(sql, params).fetchall()


class CowoncyChartTests(unittest.IsolatedAsyncioTestCase):
    first_id = "100000000000000001"
    second_id = "100000000000000002"
    yesterday = "2026-11-23"
    today = "2026-11-24"

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.addCleanup(self.connection.close)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript("""
            CREATE TABLE cowoncy_earnings (user_id TEXT, hour INTEGER, earnings INTEGER,
                                           PRIMARY KEY (user_id, hour));
            CREATE TABLE meta_data (key TEXT PRIMARY KEY, value INTEGER);
            CREATE TABLE user_stats (user_id TEXT PRIMARY KEY, cowoncy INTEGER);
        """)
        # Import the database class with an isolated worker so the fixture never opens the live database.
        package = ModuleType("_dusk_chart_fixture")
        package.__path__ = []
        package.worker = SimpleNamespace(databaseWorker=lambda: ChartWorker(self.connection))
        source = Path(__file__).resolve().parents[1] / "core" / "database" / "database.py"
        spec = importlib.util.spec_from_file_location(f"{package.__name__}.database", source)
        self.module = importlib.util.module_from_spec(spec)
        with patch.dict(sys.modules, {package.__name__: package}):
            spec.loader.exec_module(self.module)
        self.connection.execute("INSERT INTO meta_data VALUES (?, ?)",
                                (self.module.COWONCY_DATE_KEY, self.yesterday))
        self.connection.executemany("INSERT INTO cowoncy_earnings VALUES (?, ?, ?)",
                                    [(self.first_id, 1, 120), (self.second_id, 1, -90)])
        self.connection.executemany("INSERT INTO user_stats VALUES (?, 0)",
                                    [(self.first_id,), (self.second_id,)])
        self.date = self.enterContext(patch.object(self.module.utils, "get_date", return_value=self.yesterday))
        self.hour = self.enterContext(patch.object(self.module.utils, "get_hour", return_value=2))

    def database_for(self, user_id):
        return self.module.Database(SimpleNamespace(
            user=SimpleNamespace(id=int(user_id)), stats=SimpleNamespace(net_earnings=0, balance=500),
        ))

    def earnings(self, user_id):
        return [row["earnings"] for row in self.connection.execute(
            "SELECT earnings FROM cowoncy_earnings WHERE user_id = ? ORDER BY hour", (user_id,),
        )]

    async def test_rollover_after_restart_clears_each_account_independently(self):
        first, second = self.database_for(self.first_id), self.database_for(self.second_id)
        await first.populate_cowoncy_earnings()
        await second.populate_cowoncy_earnings()
        # Opening a database created by the older app preserves existing data during the same day.
        self.assertEqual(self.earnings(self.first_id)[1:3], [120, 120])
        self.assertEqual(self.earnings(self.second_id)[1:3], [-90, -90])

        self.date.return_value = self.today
        first, second = self.database_for(self.first_id), self.database_for(self.second_id)
        await first.populate_cowoncy_earnings()
        self.assertEqual(self.earnings(self.first_id), [0] * 24)
        self.assertEqual(self.earnings(self.second_id)[1:3], [-90, -90])
        first.client.stats.net_earnings = 110
        first.update_cash_db()
        await second.populate_cowoncy_earnings()
        self.assertEqual(self.earnings(self.second_id), [0] * 24)
        self.assertEqual(self.earnings(self.first_id)[2], 110)

    async def test_first_transaction_after_midnight_starts_a_new_daily_total(self):
        first, second = self.database_for(self.first_id), self.database_for(self.second_id)
        for account in (first, second):
            await account.populate_cowoncy_earnings()
            await account.fetch_net_earnings()

        self.date.return_value = self.today
        self.hour.return_value = 0
        first.client.stats.net_earnings -= 25
        first.update_cash_db()
        self.assertEqual(first.client.stats.net_earnings, -25)
        self.assertEqual(self.earnings(self.first_id), [-25] + [0] * 23)
        self.assertEqual(self.earnings(self.second_id)[1:3], [-90, -90])

        second.client.stats.net_earnings += 60
        second.update_cash_db()
        self.assertEqual(second.client.stats.net_earnings, 60)
        self.assertEqual(self.earnings(self.second_id), [60] + [0] * 23)
        self.assertEqual(self.earnings(self.first_id)[0], -25)
