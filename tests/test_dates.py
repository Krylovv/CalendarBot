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


if __name__ == "__main__":
    unittest.main()
