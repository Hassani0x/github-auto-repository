import re
from zoneinfo import ZoneInfo


class SafetyError(RuntimeError):
    pass


def require(condition, message):
    if not condition:
        raise SafetyError(message)


def validate(cfg):
    a, r, s = (cfg[key] for key in ("automation", "repository", "security"))
    for value in (a["enabled"], a["different_count_each_day"], s["dry_run"]):
        require(type(value) is bool, "Expected boolean setting")
    require(all(value is True for value in (a["randomized_schedule"], r["private"],
                r["auto_delete"], s["verify_repository_owner"], s["verify_repository_id"],
                s["protect_existing_repositories"])), "Required safety control disabled")
    for key in ("min_daily_runs", "max_daily_runs", "minimum_interval_minutes", "concurrent_runs"):
        require(type(a[key]) is int, "Expected integer setting")
    lo, hi = a["min_daily_runs"], a["max_daily_runs"]
    require(1 <= lo <= a["target_daily_average"] <= hi <= 15, "Invalid daily range")
    require(lo < hi or not a["different_count_each_day"], "Count cannot vary")
    require(a["concurrent_runs"] == 1, "Only one dispatcher is supported")
    require(1 <= a["minimum_interval_minutes"] <= 1380 // hi, "Spacing exceeds daily capacity")
    require(type(r["delete_after_seconds"]) is int and 1 <= r["delete_after_seconds"] <= 300,
            "Retention must be 1–300 seconds")
    require(re.fullmatch(r"[a-z0-9][a-z0-9-]{0,49}-", r["prefix"]), "Invalid prefix")
    ZoneInfo(a["timezone"])


def verify(repo, run, user, prefix, controller, controller_id):
    record = run["receipt"]
    require(record and type(record["id"]) is int and record["id"] > 0, "Missing creation receipt")
    name = run["name"]
    require(re.fullmatch(re.escape(prefix) + r"[0-9]{14}-[0-9a-f]{32}", name)
            and name.endswith(run["id"]), "Unexpected temporary name")
    full = f"{user['login']}/{name}"
    require(full.casefold() != controller.casefold() and str(record["id"]) != str(controller_id),
            "Controller protected")
    require(repo["id"] == record["id"] and repo["created_at"] == record["created_at"]
            and repo["owner"]["id"] == record["owner_id"] == user["id"]
            and repo["owner"]["login"] == record["owner"] == user["login"]
            and repo["full_name"] == full and repo["name"] == record["name"] == name
            and repo["private"] is True and repo["description"] == "Lifecycle test " + run["id"],
            "Repository identity mismatch")

