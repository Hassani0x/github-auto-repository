import base64
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch
import yaml
from main import dispatch
from src.state_manager import Ledger
from src.scheduler import prepare


class Dispatcher(unittest.TestCase):
    def test_preview_and_live_repoll(self):
        raw = Path("config.yaml").read_text()
        seed = Path("lifecycle-state.json").read_bytes()
        cfg = yaml.safe_load(raw)
        cfg["automation"]["enabled"] = True
        cfg["security"]["dry_run"] = False
        old = os.getcwd()
        with TemporaryDirectory() as directory:
            try:
                os.chdir(directory)
                Path("config.yaml").write_text(yaml.safe_dump(cfg))
                Path(".ledger").mkdir()
                path = Path(".ledger/lifecycle-state.json")
                path.write_bytes(seed)
                Path("calculator").mkdir()
                Path("calculator/index.html").write_text("calculator")
                with patch("main.GitHub") as api:
                    dispatch(True)
                    api.assert_not_called()
                self.assertEqual(path.read_bytes(), seed)
                ledger = Ledger(".ledger")
                key, _ = prepare(ledger.data, 1735689600, cfg["automation"])
                due = ledger.data["days"][key][0]["scheduled"]
                with patch.object(Ledger, "git"):
                    ledger.save()
                env = dict(GITHUB_ACTIONS="true", GITHUB_REPOSITORY="owner/main",
                           LIVE_APPROVAL="owner/main", DEFAULT_BRANCH="main", GITHUB_REF="refs/heads/main",
                           GITHUB_TOKEN="fake", GH_AUTOMATION_TOKEN="fake", GITHUB_REPOSITORY_ID="42")
                control, personal = Mock(calls=1), Mock(calls=1, rate={})
                control.request.return_value = {"content":base64.b64encode(Path("config.yaml").read_bytes()).decode()}
                personal.request.return_value = {"login":"owner","id":1}

                def finish(run):
                    run["status"] = "completed"

                with patch.dict(os.environ, env), patch("main.time.time", return_value=due), \
                     patch.object(Ledger, "git"), patch("main.GitHub", side_effect=[control, personal, control]), \
                     patch("main.Manager") as manager, patch("main.DeletionAccess") as access:
                    access.return_value.app.calls = 1
                    access.return_value.client = None
                    manager.return_value.execute.side_effect = finish
                    dispatch()
                    dispatch()
                    manager.return_value.execute.assert_called_once()
                saved = Ledger(".ledger").data
                self.assertEqual(saved["days"][key][0]["status"], "completed")
                self.assertEqual([r["id"] for r in saved["days"][key]],
                                 [r["id"] for r in ledger.data["days"][key]])
            finally:
                os.chdir(old)

