import json
import shutil
import tempfile
import unittest
from pathlib import Path

from bootstrap import ROOT, prepare
from utils.config_models.settings import Settings
from utils.config_models.configs import FetchGlobalSettings


class BootstrapTests(unittest.TestCase):
    def test_fresh_install_preserves_local_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            shutil.copytree(ROOT / "config" / "examples", root / "config" / "examples")
            tokens = prepare(root)
            self.assertEqual(tokens.read_text(), "")
            path = root / "config" / "global_settings.json"
            config = json.loads(path.read_text())
            self.assertFalse(config["website"]["enableHost"])
            tokens.write_text("private local input")
            config["website"]["password"] = "existing-private-password"
            path.write_text(json.dumps(config))
            before = path.read_bytes()
            prepare(root)
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(tokens.read_text(), "private local input")

    def test_templates_are_valid_for_application_and_gambling_is_off(self):
        folder = ROOT / "config" / "examples"
        settings = json.loads((folder / "settings.json").read_text())
        Settings(settings)
        FetchGlobalSettings(json.loads((folder / "global_settings.json").read_text()))
        dashboard = json.loads((folder / "dashboard.json").read_text())
        for key in ("coinflipEnabled", "slotsEnabled", "blackjackEnabled"):
            self.assertFalse(dashboard[key])
        self.assertFalse(settings["autoWeapons"]["enabled"])
