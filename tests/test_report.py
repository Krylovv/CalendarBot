import datetime
import unittest

from support import timed_event, use_tariffs

import Report

MON = "2026-09-21T"
TAGGED = "type: automated\ntg: @ivan\nsumm: 9000\npublic: yes\n"


class ScheduleTest(unittest.TestCase):
    def due(self, *args):
        return Report.due_month(datetime.datetime(*args))

    def test_last_day_from_report_hour(self):
        self.assertIsNone(self.due(2026, 9, 30, 20, 59))
        self.assertEqual(self.due(2026, 9, 30, 21, 0), (2026, 9))
        self.assertEqual(self.due(2026, 2, 28, 23, 59), (2026, 2))

    def test_catch_up_on_first_days(self):
        self.assertEqual(self.due(2026, 10, 1, 0, 0), (2026, 9))
        self.assertEqual(self.due(2026, 10, 3, 23, 0), (2026, 9))
        self.assertEqual(self.due(2027, 1, 2, 12, 0), (2026, 12))
        self.assertIsNone(self.due(2026, 10, 4, 12, 0))
        self.assertIsNone(self.due(2026, 9, 22, 21, 0))

    def test_sheet_title(self):
        self.assertEqual(Report.sheet_title(2026, 9), "Сентябрь 2026")


class RowsTest(unittest.TestCase):
    def setUp(self):
        use_tariffs(self)

    def test_published_and_manual_rents(self):
        untagged_bot = "type: automated\ntg: @maria\nsumm: 7000\n"
        events = [
            timed_event(MON + "19:00:00+03:00", MON + "21:00:00+03:00", description=TAGGED),
            # Published by hand, no recorded sum: estimated from tariffs
            timed_event(
                "2026-09-02T17:30:00+03:00",
                "2026-09-02T19:30:00+03:00",
                summary="Пётр",
                description="public: yes",
            ),
            # Made by hand, unknown if confirmed: listed with an estimate
            timed_event(MON + "10:00:00+03:00", MON + "12:00:00+03:00", summary="Анна"),
            # Made by hand with a sum recorded in /monthly_income
            timed_event(
                "2026-09-22T19:00:00+03:00",
                "2026-09-22T20:00:00+03:00",
                summary="Олег",
                private={"summ": "5000"},
            ),
            # Bot bookings without the tag are not confirmed
            timed_event(
                MON + "12:00:00+03:00",
                MON + "13:00:00+03:00",
                summary="Мария (не обработана)",
                description=untagged_bot,
            ),
            timed_event(
                MON + "13:00:00+03:00",
                MON + "14:00:00+03:00",
                summary="Мария",
                description=untagged_bot,
            ),
            # Made by hand but marked unconfirmed
            timed_event(
                MON + "14:00:00+03:00", MON + "15:00:00+03:00", summary="Ольга (не обработана)"
            ),
            # Too long to be a rental
            timed_event(MON + "00:00:00+03:00", "2026-09-23T00:00:00+03:00", summary="Отпуск"),
            # Marked "not a rent"
            timed_event(
                MON + "15:00:00+03:00",
                MON + "16:00:00+03:00",
                description="public: yes",
                private={"summ": "0"},
            ),
            timed_event(MON + "16:00:00+03:00", MON + "17:00:00+03:00", private={"summ": "0"}),
            {
                "summary": "Праздник",
                "description": "public: yes",
                "start": {"date": "2026-09-27"},
                "end": {"date": "2026-09-28"},
            },
        ]
        rows = Report.report_rows(events)
        manual = "Не автоматизированная аренда"
        self.assertEqual(
            rows,
            [
                ("Пётр", datetime.date(2026, 9, 2), 8750, "сумма по тарифам"),
                ("Анна", datetime.date(2026, 9, 21), 8000, manual),
                ("Иван", datetime.date(2026, 9, 21), 9000, ""),
                ("Олег", datetime.date(2026, 9, 22), 5000, manual),
            ],
        )
        self.assertEqual(Report.totals(rows), (4, 30750, 6150))


class SheetTest(unittest.TestCase):
    def values(self, row):
        return [cell.get("userEnteredValue") for cell in row["values"]]

    def test_layout_and_formulas(self):
        rows = [
            ("=Иван", datetime.date(2026, 9, 23), 9000, ""),
            ("Пётр", datetime.date(2026, 9, 24), 8750, "сумма по тарифам"),
        ]
        add, fill, _ = Report.sheet_requests(7, "Сентябрь 2026", rows)
        self.assertEqual(
            add, {"addSheet": {"properties": {"sheetId": 7, "title": "Сентябрь 2026"}}}
        )
        data = fill["updateCells"]["rows"]
        self.assertEqual([value["stringValue"] for value in self.values(data[0])], Report.HEADER)
        self.assertEqual(
            self.values(data[1]),
            [
                # A name is never a formula
                {"stringValue": "=Иван"},
                {"numberValue": 46288},
                {"numberValue": 9000},
                None,
                {"formulaValue": "=C2*20/100"},
            ],
        )
        self.assertEqual(self.values(data[2])[3], {"stringValue": "сумма по тарифам"})
        self.assertEqual(
            self.values(data[3]),
            [
                {"stringValue": "Итого"},
                None,
                {"formulaValue": "=SUM(C2:C3)"},
                None,
                {"formulaValue": "=SUM(E2:E3)"},
            ],
        )

    def test_empty_month(self):
        _, fill, _ = Report.sheet_requests(7, "Сентябрь 2026", [])
        total = fill["updateCells"]["rows"][1]
        self.assertEqual(self.values(total)[2], {"numberValue": 0})


if __name__ == "__main__":
    unittest.main()
