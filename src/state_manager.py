import hashlib
import hmac
import json
import os
import subprocess
from pathlib import Path

from .security import require


def empty():
    return {"version": 1, "days": {}, "last_start": 0, "timezone": None, "usage": {}}


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class Ledger:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / "lifecycle-state.json"
        envelope = json.loads(self.path.read_text(encoding="utf-8"))
        self.data = envelope["data"]
        require(hmac.compare_digest(envelope["sha256"], digest(self.data))
                and self.data["version"] == 1, "Ledger integrity check failed")
        active = 0
        ids = set()
        for runs in self.data["days"].values():
            require(1 <= len(runs) <= 15, "Invalid persisted count")
            for run in runs:
                require(run["id"] not in ids, "Duplicate execution ID")
                ids.add(run["id"])
                active += run["status"] == "active"
        require(active <= 1, "Multiple active executions")

    def git(self, *args, check=True):
        return subprocess.run(["git", "-C", str(self.directory), *args], check=check)

    def save(self):
        envelope = {"data": self.data, "sha256": digest(self.data)}
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(envelope, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, self.path)
        self.git("add", "--", self.path.name)
        diff = self.git("diff", "--cached", "--quiet", "--", self.path.name, check=False)
        if diff.returncode == 0:
            return
        if diff.returncode != 1:
            diff.check_returncode()
        self.git("-c", "user.name=Lifecycle dispatcher", "-c", "user.email=dispatcher@users.noreply.github.com",
                 "commit", "-m", "Checkpoint repository lifecycle")
        # A rejected or ambiguous push aborts the process before any further API mutation.
        self.git("push", "origin", "HEAD:refs/heads/automation-state")

