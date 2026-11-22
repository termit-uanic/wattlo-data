import json
import os
import tempfile
import unittest
from datetime import datetime, timezone

from collector import build, regions, sources

NOW = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)
TODAY, TOMORROW = "2026-11-21", "2026-11-22"
LVIV = next(r for r in regions.REGIONS if r.slug == "lvivska-oblast")


def day(*off):
    s = ["0"] * 48
    for i in off:
        s[i] = "1"
    return "".join(s)


def result(region, **per_queue):
    return {q: {TODAY: per_queue.get(q, day())} for q in region.queues}


class Merge(unittest.TestCase):
    def fetcher(self, answers):
        def fetch(source, region, now=None):
            a = answers[source]
            if isinstance(a, Exception):
                raise a
            return a
        return fetch

    def test_the_first_usable_source_wins(self):
        a = {"bezsvitla": result(LVIV, **{"1.1": day(4, 5)}), "oe_data": result(LVIV, **{"1.1": day(4, 5)})}
        primary, res, report = build.collect_region(LVIV, self.fetcher(a), NOW)
        self.assertEqual(primary, "bezsvitla")
        self.assertEqual([e["ok"] for e in report], [True, True])
        self.assertEqual(report[1]["agreement"], 1.0)

    def test_a_failed_source_is_skipped_and_reported(self):
        a = {"bezsvitla": sources.SourceError("down"), "oe_data": result(LVIV)}
        primary, res, report = build.collect_region(LVIV, self.fetcher(a), NOW)
        self.assertEqual(primary, "oe_data")
        self.assertFalse(report[0]["ok"])
        self.assertIn("down", report[0]["error"])

    def test_a_source_without_today_is_not_usable(self):
        stale = {q: {"2026-11-20": day()} for q in LVIV.queues}
        a = {"bezsvitla": stale, "oe_data": result(LVIV)}
        primary, _, report = build.collect_region(LVIV, self.fetcher(a), NOW)
        self.assertEqual(primary, "oe_data")
        self.assertIn("today", report[0]["error"])

    def test_nothing_usable(self):
        a = {"bezsvitla": sources.SourceError("down"), "oe_data": sources.SourceError("old")}
        primary, res, report = build.collect_region(LVIV, self.fetcher(a), NOW)
        self.assertIsNone(primary)
        self.assertIsNone(res)

    def test_disagreement_is_measured(self):
        a = {"bezsvitla": result(LVIV, **{"1.1": day(4)}), "oe_data": result(LVIV)}
        _, _, report = build.collect_region(LVIV, self.fetcher(a), NOW)
        self.assertEqual(report[1]["agreement"], round(11 / 12, 3))

    def test_a_may_be_off_slot_is_not_a_disagreement(self):
        a, b = day(4), day(4)
        b = b[:5] + "2" + b[6:]
        self.assertTrue(build.same_power(a, b))
        self.assertFalse(build.same_power(day(4), day(5)))


class Files(unittest.TestCase):
    def test_updated_at_moves_only_with_the_schedule(self):
        res = result(LVIV)
        doc = build.region_file(LVIV, "bezsvitla", res, [], None, NOW)
        self.assertEqual(doc["updatedAt"], "2026-11-21T10:00:00Z")
        later = datetime(2026, 11, 21, 12, 0, tzinfo=timezone.utc)
        same = build.region_file(LVIV, "bezsvitla", res, [], doc, later)
        self.assertEqual(same["updatedAt"], "2026-11-21T10:00:00Z")
        changed = build.region_file(LVIV, "bezsvitla", result(LVIV, **{"1.1": day(3)}), [], doc, later)
        self.assertEqual(changed["updatedAt"], "2026-11-21T12:00:00Z")

    def test_the_document(self):
        res = {q: {TODAY: day(), TOMORROW: day(1)} for q in LVIV.queues}
        doc = build.region_file(LVIV, "bezsvitla", res, [], None, NOW)
        self.assertEqual(doc["version"], 1)
        self.assertEqual(list(doc["days"]), [TODAY, TOMORROW])
        self.assertEqual(set(doc["days"][TODAY]), set(LVIV.queues))
        self.assertTrue(all(len(s) == 48 for d in doc["days"].values() for s in d.values()))

    def test_run_writes_the_files_and_no_clock_in_them(self):
        def fetch(source, region, now=None):
            return result(region)
        with tempfile.TemporaryDirectory() as out, tempfile.TemporaryDirectory() as site:
            failing = build.run(out, site, fetch, NOW)
            self.assertEqual(failing, 0)
            with open(os.path.join(out, "regions", "kyiv.json"), encoding="utf-8") as f:
                self.assertNotIn("checkedAt", json.load(f))
            with open(os.path.join(site, "regions", "kyiv.json"), encoding="utf-8") as f:
                self.assertEqual(json.load(f)["checkedAt"], "2026-11-21T10:00:00Z")
            with open(os.path.join(out, "index.json"), encoding="utf-8") as f:
                self.assertEqual(len(json.load(f)["regions"]), 22)

    def test_a_region_without_a_source_keeps_its_old_file_and_counts_as_failing_without_today(self):
        calls = {"n": 0}
        def fetch(source, region, now=None):
            calls["n"] += 1
            if calls["n"] > 60:  # the second run: everything is down
                raise sources.SourceError("down")
            return result(region)
        with tempfile.TemporaryDirectory() as out:
            self.assertEqual(build.run(out, None, fetch, NOW), 0)
            # the next day nothing answers: the files are kept, but they have no day of today
            next_day = datetime(2026, 11, 22, 10, 0, tzinfo=timezone.utc)
            self.assertEqual(build.run(out, None, fetch, next_day), 22)
            with open(os.path.join(out, "regions", "kyiv.json"), encoding="utf-8") as f:
                doc = json.load(f)
            self.assertIn(TODAY, doc["days"])
            self.assertIsNone(doc["source"])


if __name__ == "__main__":
    unittest.main()
