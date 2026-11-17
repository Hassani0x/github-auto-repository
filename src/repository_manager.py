import base64
import re
import time
from datetime import UTC, datetime

from .github_client import APIError
from .security import SafetyError, require, verify


class Manager:
    def __init__(self, api, user, config, controller, controller_id, guard, save, content, scoped):
        self.api, self.user, self.cfg = api, user, config
        self.controller, self.controller_id = controller, controller_id
        self.guard, self.save, self.content = guard, save, content
        self.scoped = scoped

    def checkpoint(self, run, phase):
        run["phase"] = phase
        self.save()

    def identity(self, run, repo):
        verify(repo, run, self.user, self.cfg["prefix"], self.controller, self.controller_id)

    def finish(self, run, status, error=None):
        run.update(status=status, error=error, duration=max(0, round(time.time() - run["actual"], 2)))
        self.save()

    def execute(self, run):
        if not run["name"]:
            stamp = datetime.fromtimestamp(run["actual"], UTC).strftime("%Y%m%d%H%M%S")
            run["name"] = self.cfg["prefix"] + stamp + "-" + run["id"]
        path = f"/repos/{self.user['login']}/{run['name']}"
        try:
            self.advance(run, path)
        except (SafetyError, KeyError, ValueError, TypeError) as exc:
            reason = str(exc) if isinstance(exc, SafetyError) else "Invalid API response or receipt"
            self.finish(run, "failed", reason)
            raise SafetyError(reason) from None
        except APIError as exc:
            # Preserve the phase for read-side reconciliation by the next dispatcher.
            run["error"] = str(exc)
            run["retry_at"] = exc.retry_at
            run["api_failures"] = run.get("api_failures", 0) + 1
            if run["api_failures"] >= 3:
                self.finish(run, "failed", str(exc) + ". Manual reconciliation required")
            else:
                self.save()
            raise

    def advance(self, run, path):
        phase = run["phase"]
        if phase == "claimed":
            require(self.api.lookup(path) is None, "Generated name already exists")
            self.guard()
            self.checkpoint(run, "creating")
            repo = self.api.request("POST", "/user/repos", {
                "name": run["name"], "private": True, "auto_init": False,
                "description": "Lifecycle test " + run["id"]}, expected=201)
            run["receipt"] = dict(id=repo["id"], created_at=repo["created_at"], name=repo["name"],
                                  owner_id=repo["owner"]["id"], owner=repo["owner"]["login"])
            self.identity(run, repo)
            self.checkpoint(run, "created")
        elif phase == "creating":
            found = self.api.lookup(path)
            raise SafetyError("Creation response unavailable. Manual review: " +
                              ("name exists" if found else "name absent"))

        if run["phase"] == "created":
            self.identity(run, self.api.request("GET", path))
            self.guard()
            self.checkpoint(run, "uploading")
            result = self.api.request("PUT", path + "/contents/index.html", {
                "message": "Install calculator", "content": base64.b64encode(self.content).decode()},
                expected=201)
            run.update(upload=True, commit=result["commit"]["sha"])
            self.checkpoint(run, "uploaded")

        if run["phase"] == "uploading":
            # The upload may already have committed. Never issue a second PUT.
            self.identity(run, self.api.request("GET", path))
            history = self.api.lookup(path + "/commits?path=index.html&per_page=2")
            require(history and len(history) == 1, "Unconfirmed upload. Inspect repository manually")
            run.update(upload=True, commit=history[0]["sha"])
            self.checkpoint(run, "uploaded")

        if run["phase"] == "uploaded":
            sha = run["commit"]
            require(re.fullmatch("[0-9a-f]{40,64}", sha), "Malformed commit identifier")
            self.identity(run, self.api.request("GET", path))
            commit = self.api.request("GET", path + "/commits/" + sha)
            file = self.api.request("GET", path + "/contents/index.html?ref=" + sha)
            require(commit["sha"] == sha and file["path"] == "index.html" and
                    base64.b64decode(file["content"]) == self.content, "Commit or file mismatch")
            run.update(verified=True, delete_at=time.time() + self.cfg["delete_after_seconds"])
            self.checkpoint(run, "verified")

        if run["phase"] in ("verified", "deleting", "acknowledged"):
            time.sleep(max(0, min(300, run["delete_at"] - time.time())))
            require(time.time() >= run["delete_at"], "Retention period has not elapsed")
            self.guard()
            current = self.api.lookup(path)
            if run["phase"] == "acknowledged":
                require(current is None, "Deletion acknowledged but name still exists")
            else:
                require(current is not None, "Repository absent without deletion acknowledgement")
                self.identity(run, current)
                if run["phase"] != "deleting":
                    self.checkpoint(run, "deleting")
                deletion = self.scoped(run["receipt"]["id"])
                self.guard()
                self.identity(run, deletion.request("GET", path))
                deletion.request("DELETE", path, expected=204)
                self.checkpoint(run, "acknowledged")
                require(self.api.lookup(path) is None, "Deletion could not be verified")
            run["deleted"] = True
            self.finish(run, "completed")

