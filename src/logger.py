import json
from datetime import UTC, datetime


def report(day, runs, usage):
    print("Schedule", day, json.dumps([datetime.fromtimestamp(r["scheduled"], UTC).isoformat()
                                       for r in runs]))
    counts = {s: sum(r["status"] == s for r in runs) for s in ("completed", "failed", "missed")}
    print(json.dumps(dict(date=day, planned=len(runs), **counts,
                          remaining=len(runs) - sum(counts.values()),
                          created=sum(bool(r["receipt"]) for r in runs),
                          deleted=sum(r["deleted"] for r in runs), api=usage)))

