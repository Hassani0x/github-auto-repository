import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from src.security import SafetyError
from src.state_manager import Ledger

def git(*args):
    subprocess.run(["git", *map(str,args)], capture_output=True, check=True)


class Persistence(unittest.TestCase):
    def test_corruption(self):
        with tempfile.TemporaryDirectory() as root:
            data = json.loads(Path("lifecycle-state.json").read_text())
            data["data"]["last_start"] = 1
            Path(root, "lifecycle-state.json").write_text(json.dumps(data))
            with self.assertRaises(SafetyError):
                Ledger(root)

    def test_restart_and_competing_push(self):
        with tempfile.TemporaryDirectory() as root:
            remote, a, b = (Path(root, n) for n in ("remote", "a", "b"))
            git("init", "--bare", "--initial-branch=automation-state", remote)
            git("clone", remote, a)
            (a / "lifecycle-state.json").write_bytes(Path("lifecycle-state.json").read_bytes())
            ledger = Ledger(a)
            ledger.save()
            git("clone", remote, b)
            stale = Ledger(b)
            ledger.data["last_start"] = 10
            ledger.save()
            self.assertEqual(Ledger(a).data["last_start"], 10)
            stale.data["last_start"] = 20
            with self.assertRaises(subprocess.CalledProcessError):
                stale.save()

