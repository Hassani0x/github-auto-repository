import argparse
import base64
import copy
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo
from datetime import datetime

import yaml

from src.github_client import GitHub, APIError
from src.deletion_access import DeletionAccess
from src.logger import report
from src.repository_manager import Manager
from src.scheduler import prepare
from src.security import SafetyError, require, validate
from src.state_manager import Ledger, empty


def dispatch(preview=False):
    raw = Path("config.yaml").read_bytes()
    cfg = yaml.safe_load(raw)
    validate(cfg)
    a = cfg["automation"]
    preview = preview or cfg["security"]["dry_run"]
    if not a["enabled"] and not preview:
        print("Automation disabled")
        return
    ledger = Ledger(".ledger") if Path(".ledger").exists() else None
    state = copy.deepcopy(ledger.data) if ledger else empty()
    require(preview or ledger, "Live mode requires the persistent ledger")
    if state["timezone"] not in (None, a["timezone"]):
        active = any(r["status"] == "active" for runs in state["days"].values() for r in runs)
        local_day = datetime.now(ZoneInfo(a["timezone"])).date().isoformat()
        require(not active and local_day > max(state["days"], default="")
                and time.time() - state["last_start"] >= 86400,
                "Timezone change requires an idle ledger and a fresh local day")
    state["timezone"] = a["timezone"]
    now = int(time.time())
    day, due = prepare(state, now, a)
    runs = state["days"][day]
    if ledger:
        for prior, records in state["days"].items():
            if prior != day and records != ledger.data["days"][prior]:
                report(prior, records, state["usage"].get(prior, {}))
    report(day, runs, state["usage"].get(day, {}))
    if preview:
        print("Dry run. Eligible execution:", due["id"] if due else "none")
        return
    env = os.environ
    controller = env["GITHUB_REPOSITORY"]
    require(env.get("GITHUB_ACTIONS") == "true" and env.get("LIVE_APPROVAL") == controller
            and env.get("GITHUB_REF") == "refs/heads/" + env["DEFAULT_BRANCH"],
            "Live approval or default branch verification failed")
    control = GitHub(env["GITHUB_TOKEN"])
    def guard():
        file = control.request("GET", f"/repos/{controller}/contents/config.yaml?ref=" +
                               quote(env["DEFAULT_BRANCH"], safe=""))
        require(base64.b64decode(file["content"]) == raw, "Configuration changed. Dispatch halted")

    if state != ledger.data:
        ledger.data = state
        ledger.save()
    active = next((r for group in state["days"].values() for r in group if r["status"] == "active"), None)
    run = active or due
    if not run or run.get("retry_at", 0) > now or state.get("retry_at", 0) > now:
        return
    api = GitHub(env.get("GH_AUTOMATION_TOKEN"))
    access = None
    usage = state["usage"].setdefault(day, {"requests": 0, "rate": {}})
    def save():
        ledger.data = state
        ledger.save()
    try:
        if not active:
            started = int(time.time())
            if datetime.fromtimestamp(started, ZoneInfo(a["timezone"])).date().isoformat() != day:
                return
            run.update(status="active", actual=started, phase="claimed")
            state["last_start"] = started
            save()
        if run["phase"] == "claimed" and (run not in runs or
                now - run["scheduled"] >= a["minimum_interval_minutes"] * 60):
            run.update(status="missed", error="Claim expired before creation")
            save()
            return
        guard()
        user = api.request("GET", "/user")
        require(user["login"].casefold() == controller.split("/")[0].casefold(),
                "Token owner must own the controller")
        access = DeletionAccess(user, env.get("DELETION_APP_CLIENT_ID"), env.get("DELETION_APP_KEY"))
        Manager(api, user, cfg["repository"], controller, env["GITHUB_REPOSITORY_ID"],
                guard, save, Path("calculator/index.html").read_bytes(), access.scoped).execute(run)
    except APIError as exc:
        state["retry_at"] = exc.retry_at
        run["error"] = str(exc)
        if run["phase"] == "claimed":
            run.update(status="failed", duration=int(time.time()) - run["actual"])
        raise
    except SafetyError as exc:
        if run["phase"] == "claimed":
            run.update(status="failed", error=str(exc), duration=int(time.time()) - run["actual"])
        raise
    finally:
        # Record metrics only when no checkpoint write failed. Never mask a failed push.
        if not isinstance(sys.exc_info()[1], (subprocess.SubprocessError, OSError)):
            usage["requests"] += api.calls + control.calls
            if access:
                usage["requests"] += access.app.calls + (access.client.calls if access.client else 0)
            usage["rate"] = api.rate
            save()
        report(day, runs, usage)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    dispatch(parser.parse_args().dry_run)

