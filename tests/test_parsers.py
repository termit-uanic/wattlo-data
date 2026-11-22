import os
import unittest
from datetime import date, datetime, timezone

from collector import regions, sources

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


class Bezsvitla(unittest.TestCase):
    def test_kyiv_sub_queue(self):
        r = sources.parse_bezsvitla(fixture("bezsvitla_kyiv.html"), regions.KYIV_QUEUES, date(2026, 11, 20))
        self.assertEqual(sorted(r), ["1.1", "10.1", "11.1"])
        # the card has no schedule for tomorrow yet
        self.assertEqual(list(r["10.1"]), ["2026-11-20"])
        self.assertEqual(r["10.1"]["2026-11-20"], "0" * 22 + "1" * 10 + "0" * 10 + "1" * 6)

    def test_queue_1_1_is_not_11_1(self):
        r = sources.parse_bezsvitla(fixture("bezsvitla_kyiv.html"), regions.KYIV_QUEUES, date(2026, 11, 20))
        self.assertNotEqual(r["1.1"]["2026-11-20"], r["11.1"]["2026-11-20"])
        self.assertEqual(r["1.1"]["2026-11-20"][9:15], "111111")  # no power 04:30-07:30

    def test_ternopil_odd_queues(self):
        r = sources.parse_bezsvitla(fixture("bezsvitla_ternopil.html"), regions.TERNOPIL_QUEUES, date(2026, 11, 21))
        for q in ("1.1", "7.2", "12.2"):
            self.assertEqual(r[q]["2026-11-21"], "0" * 48, q)

    def test_chernivtsi_groups(self):
        r = sources.parse_bezsvitla(fixture("bezsvitla_chernivtsi.html"), regions.CHERNIVTSI_QUEUES, date(2026, 11, 21))
        self.assertEqual(r["1"]["2026-11-21"], "0" * 48)
        self.assertEqual(r["5"]["2026-11-21"], "1" + "0" * 47)
        self.assertEqual(r["9"]["2026-11-21"], "0" + "1" * 4 + "0" * 43)
        self.assertEqual(r["12"]["2026-11-21"], "11" + "0" * 46)  # "Група 12" is not "Група 1"
        self.assertNotIn("2", r)

    def test_a_queue_that_is_not_there_is_absent(self):
        r = sources.parse_bezsvitla(fixture("bezsvitla_kyiv.html"), ["2.1"], date(2026, 11, 20))
        self.assertEqual(r, {})


class Yasno(unittest.TestCase):
    def test_today_from_slots(self):
        r = sources.parse_yasno(fixture("yasno_kyiv.json"), regions.KYIV_QUEUES)
        # off 01:00-05:00, 11:30-15:30 and 22:00-24:00
        expected = "00" + "1" * 8 + "0" * 13 + "1" * 8 + "0" * 13 + "1" * 4
        self.assertEqual(r["1.1"], {"2026-11-21": expected})

    def test_no_outages_and_the_days_without_a_schedule(self):
        text = """{"3.1": {"today": {"slots": [], "date": "2026-11-21T00:00:00+02:00", "status": "NoOutages"},
            "tomorrow": {"slots": [], "date": "2026-11-22T00:00:00+02:00", "status": "EmergencyShutdowns"}}}"""
        r = sources.parse_yasno(text, ["3.1", "4.1"])
        self.assertEqual(r, {"3.1": {"2026-11-21": "0" * 48}})


class Mirror(unittest.TestCase):
    now = datetime(2026, 11, 21, 10, 0, tzinfo=timezone.utc)

    def test_hours_and_halves(self):
        r = sources.parse_mirror(fixture("mirror_poltava.json"), ["1.1", "2.1"], self.now)
        s = r["1.1"]["2026-11-21"]
        self.assertEqual(len(s), 48)
        self.assertEqual(s[30:36], "111111")      # 15:00-18:00 no
        self.assertEqual(s[36:38], "20")          # 18:00-19:00 mfirst: may be off, then on
        self.assertEqual(s[42:46], "1111")        # 21:00-23:00 no
        self.assertEqual(s[46:48], "12")          # 23:00-24:00 msecond: off, then may be off
        self.assertEqual(s[:30], "0" * 30)

    def test_the_day_is_the_one_in_kyiv(self):
        # the key 1795212000 is 22:00 UTC on 20 November: the midnight of the 21st in Kyiv
        self.assertEqual(list(sources.parse_mirror(fixture("mirror_poltava.json"), ["1.1"], self.now)["1.1"]), ["2026-11-21"])

    def test_a_very_old_file_is_refused(self):
        with self.assertRaises(sources.SourceError):
            sources.parse_mirror(fixture("mirror_poltava.json"), ["1.1"], datetime(2026, 11, 24, 10, tzinfo=timezone.utc))

    def test_a_file_without_today_is_refused(self):
        with self.assertRaises(sources.SourceError):
            sources.parse_mirror(fixture("mirror_poltava.json"), ["1.1"], datetime(2026, 11, 22, 10, tzinfo=timezone.utc))

    def test_last_updated_as_a_number(self):
        text = '{"lastUpdated": 1795257108, "fact": {"data": {"1795212000": {"GPV1.1": {"1": "first", "2": "second"}}}}}'
        r = sources.parse_mirror(text, ["1.1"], datetime.fromtimestamp(1795257108 + 60, timezone.utc))
        self.assertEqual(r["1.1"]["2026-11-21"][:4], "1001")

    def test_an_unknown_queue_is_absent(self):
        self.assertEqual(sources.parse_mirror(fixture("mirror_poltava.json"), ["9.9"], self.now), {})


class Regions(unittest.TestCase):
    def test_the_table(self):
        self.assertEqual(len(regions.REGIONS), 22)
        self.assertEqual(len({r.slug for r in regions.REGIONS}), 22)
        for r in regions.REGIONS:
            self.assertIn("bezsvitla", r.sources, r.slug)  # every region has its page there
            if "yasno" in r.sources:
                self.assertIsNotNone(r.yasno, r.slug)
            if any(s in regions.RAW_BASE for s in r.sources):
                self.assertIsNotNone(r.data_file, r.slug)
        self.assertEqual(len(regions.KYIV_QUEUES), 60)
        self.assertEqual(len(regions.TERNOPIL_QUEUES), 14)


if __name__ == "__main__":
    unittest.main()
