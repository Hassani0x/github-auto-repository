import math
import random
import uuid
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

RNG = random.SystemRandom()


def plan(day, settings, previous=None, last_slot=0, rng=RNG):
    zone = ZoneInfo(settings["timezone"])
    start = int(datetime.combine(day, time.min, zone).timestamp())
    end = int(datetime.combine(day + timedelta(days=1), time.min, zone).timestamp())
    spacing = settings["minimum_interval_minutes"] * 60
    start = max(start, last_slot + spacing)
    counts = [n for n in range(settings["min_daily_runs"], settings["max_daily_runs"] + 1)
              if n != previous or not settings["different_count_each_day"]]
    weights = [math.exp(-abs(n - settings["target_daily_average"]) / 1.05) for n in counts]
    count = rng.choices(counts, weights)[0]
    # Stratify the free time, then insert the mandatory gap between strata.
    free = end - start - (count - 1) * spacing
    if free < count:
        raise ValueError("Schedule cannot fit this local day")
    runs = []
    for i in range(count):
        offset = rng.randrange(i * free // count, (i + 1) * free // count)
        runs.append(dict(id=uuid.uuid4().hex, scheduled=start + i * spacing + offset,
                         status="pending", actual=None, name=None, receipt=None, upload=False,
                         verified=False, deleted=False, duration=None, error=None))
    return runs


def prepare(state, now, settings):
    day = datetime.fromtimestamp(now, UTC).astimezone(ZoneInfo(settings["timezone"])).date()
    key = day.isoformat()
    days = state["days"]
    if key not in days:
        previous = max(days, default=None)
        if previous and previous > key:
            raise ValueError("Clock moved behind persisted schedule")
        prior = days.get(previous, [])
        days[key] = plan(day, settings, len(prior) or None, prior[-1]["scheduled"] if prior else 0)
    gap = settings["minimum_interval_minutes"] * 60
    due = None
    for date, runs in sorted(days.items()):
        for run in runs:
            if run["status"] != "pending" or run["scheduled"] > now:
                continue
            if date != key or now - run["scheduled"] >= gap:
                run["status"] = "missed"
            elif now - state["last_start"] >= gap:
                due = run
    return key, due

