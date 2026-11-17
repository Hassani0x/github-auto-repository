import random
import unittest
from datetime import date, timedelta

import yaml
from pathlib import Path
from src.scheduler import plan, prepare
from src.state_manager import empty

CFG = yaml.safe_load(Path("config.yaml").read_text())["automation"]


class Scheduling(unittest.TestCase):
    def test_three_years_with_dst(self):
        settings = dict(CFG, timezone="America/Los_Angeles")
        rng = random.Random(42)
        counts, last = [], 0
        for i in range(1096):
            runs = plan(date(2024, 1, 1) + timedelta(days=i), settings,
                        counts[-1] if counts else None, last, rng)
            count = len(runs)
            self.assertIn(count, range(7, 16))
            self.assertNotEqual(count, counts[-1] if counts else None)
            counts.append(count)
            for run in runs:
                self.assertGreaterEqual(run["scheduled"] - last, 1800)
                last = run["scheduled"]
        self.assertAlmostEqual(sum(counts) / len(counts), 10, delta=.35)

    def test_random_times(self):
        self.assertNotEqual([r["scheduled"] for r in plan(date.today(), CFG)],
                            [r["scheduled"] for r in plan(date.today(), CFG)])

    def test_repeat_poll_and_delay(self):
        state = empty()
        key, _ = prepare(state, 1735689600, CFG)
        runs = state["days"][key]
        due_at = runs[0]["scheduled"]
        self.assertIs(prepare(state, due_at, CFG)[1], runs[0])
        state["last_start"] = due_at
        runs[0]["status"] = "completed"
        self.assertIsNone(prepare(state, due_at, CFG)[1])
        prepare(state, 1735689600 + 86400, CFG)
        self.assertTrue(all(r["status"] == "missed" for r in runs[1:]))

