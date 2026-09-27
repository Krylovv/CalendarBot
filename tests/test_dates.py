import datetime
import unittest

import support  # noqa: F401  (adds app/ to sys.path)

import Dates


class DatesTest(unittest.TestCase):
    def test_next_week_from_monday_is_the_following_week(self):
        start, end = Dates.next_week_range(datetime.date(2026, 9, 21))  # Monday
        self.assertEqual(start, datetime.datetime(2026, 9, 28))
        self.assertEqual(end, datetime.datetime(2026, 10, 5))

    def test_next_week_from_sunday_starts_tomorrow(self):
        start, end = Dates.next_week_range(datetime.date(2026, 9, 27))  # Sunday
        self.assertEqual(start, datetime.datetime(2026, 9, 28))
        # Includes all of Sunday 04.10
        self.assertEqual(end - start, datetime.timedelta(days=7))

    def test_month_range_includes_last_day(self):
        self.assertEqual(
            Dates.month_range(2026, 9),
            (datetime.datetime(2026, 9, 1), datetime.datetime(2026, 10, 1)),
        )
        self.assertEqual(Dates.month_range(2026, 12)[1], datetime.datetime(2027, 1, 1))

    def test_rfc3339_uses_moscow_offset(self):
        self.assertEqual(
            Dates.rfc3339(datetime.datetime(2026, 9, 30, 0, 0)), "2026-09-30T00:00:00+03:00"
        )

    def test_parse_api_time_converts_to_moscow(self):
        self.assertEqual(
            Dates.parse_api_time("2026-09-22T16:30:00Z"), datetime.datetime(2026, 9, 22, 19, 30)
        )

    def test_all_day_event_has_no_bounds(self):
        self.assertIsNone(Dates.event_bounds({"start": {"date": "2026-09-22"}}))

    def test_formatting(self):
        start, end = datetime.datetime(2026, 9, 23, 19, 30), datetime.datetime(2026, 9, 23, 22, 0)
        self.assertEqual(Dates.format_span(start, end), "23.09 ср 19:30–22:00")
        self.assertEqual(Dates.format_hours(start, end), "2,5 ч")


class ParseMoveTest(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 27)

    def test_keeps_duration_when_hours_missing(self):
        self.assertEqual(
            Dates.parse_move("25.10 19:30", self.TODAY),
            (datetime.datetime(2026, 10, 25, 19, 30), None),
        )

    def test_hours_year_and_bare_hour(self):
        self.assertEqual(
            Dates.parse_move(" 5.1.2027 19 2,5 ", self.TODAY),
            (datetime.datetime(2027, 1, 5, 19), 2.5),
        )

    def test_year_is_the_nearest_one(self):
        self.assertEqual(
            Dates.parse_day("05.01", datetime.date(2026, 12, 20)), datetime.date(2027, 1, 5)
        )
        self.assertEqual(Dates.parse_day("20.09", self.TODAY), datetime.date(2026, 9, 20))
        # No leap year nearby: the year has to be typed
        self.assertEqual(Dates.parse_day("29.02.28", self.TODAY), datetime.date(2028, 2, 29))
        with self.assertRaises(ValueError):
            Dates.parse_day("29.02", self.TODAY)

    def test_rejects_garbage(self):
        for text in ("завтра", "25.10", "32.10 19:00", "25.10 25:00", "25.10 19:30 три"):
            with self.assertRaises(ValueError, msg=text):
                Dates.parse_move(text, self.TODAY)


if __name__ == "__main__":
    unittest.main()
