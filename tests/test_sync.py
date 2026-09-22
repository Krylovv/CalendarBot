import unittest
from unittest import mock

from support import use_tariffs

import Spreadsheet
from Calendar import EventExists

ROW = ["Иван", "@ivan", "", "", "21-09-2026", "19:30", "2", "4"]
PROCESSED = ["x"] * 16


def bare_sheet():
    # Skip GoogleApi.__init__: no credentials needed for the sync logic
    sheet = Spreadsheet.Spreadsheets.__new__(Spreadsheet.Spreadsheets)
    sheet.SPREADSHEET_ID = "test"
    sheet.notifier = mock.Mock()
    return sheet


class SyncOnceTest(unittest.TestCase):
    def setUp(self):
        use_tariffs(self)
        self.log = []
        self.sheet = bare_sheet()
        self.sheet.update_values = lambda cell, option, values: self.log.append(
            ("mark", cell, option, values[0])
        )
        self.calendar = mock.Mock()
        self.calendar.create_event.side_effect = self.create_event
        patcher = mock.patch.object(Spreadsheet, "Calendar", return_value=self.calendar)
        patcher.start()
        self.addCleanup(patcher.stop)

    def create_event(self, result, sheet_row):
        self.log.append(("create", sheet_row, result["time"]))
        return {"id": f"cb{sheet_row}"}, []

    def rows(self, *rows):
        self.sheet.get_applications = lambda: list(rows)

    def test_marks_row_only_after_event_exists(self):
        self.rows(PROCESSED, ROW)
        self.sheet.sync_once()
        self.assertEqual(
            self.log, [("create", 2, "19:30:00"), ("mark", "P2", "USER_ENTERED", "True")]
        )
        self.sheet.notifier.new_booking.assert_called_once_with({"id": "cb2"}, [], 2)

    def test_failed_insert_leaves_row_for_next_pass(self):
        self.calendar.create_event.side_effect = TimeoutError("network")
        self.rows(ROW)
        with self.assertRaises(TimeoutError):
            self.sheet.sync_once()
        self.assertEqual(self.log, [])

    def test_bad_row_is_flagged_and_reported(self):
        self.rows(["Иван", "@ivan", "", "", "22.09.2026", "19:30", "2", "4"], ROW)
        self.sheet.sync_once()
        mark = self.log[0]
        self.assertEqual(mark[:3], ("mark", "P1", "RAW"))
        self.assertTrue(mark[3].startswith("ОШИБКА: "))
        self.sheet.notifier.row_error.assert_called_once()
        # The next row is still processed
        self.assertEqual(
            self.log[1:], [("create", 2, "19:30:00"), ("mark", "P2", "USER_ENTERED", "True")]
        )

    def test_short_row_is_flagged(self):
        self.rows(["Иван", "@ivan"])
        self.sheet.sync_once()
        self.assertEqual(self.log[0][:3], ("mark", "P1", "RAW"))
        self.calendar.create_event.assert_not_called()

    def test_duplicate_is_marked_not_recreated(self):
        self.calendar.create_event.side_effect = EventExists("cb1")
        self.calendar.find_event.return_value = {"id": "cb1"}
        self.rows(ROW)
        self.sheet.sync_once()
        self.assertEqual(self.log, [("mark", "P1", "USER_ENTERED", "True")])
        self.sheet.notifier.duplicate_booking.assert_called_once_with({"id": "cb1"}, 1)

    def test_telegram_failure_does_not_break_sync(self):
        self.sheet.notifier.new_booking.side_effect = RuntimeError("telegram down")
        self.rows(ROW, ROW)
        with mock.patch.object(Spreadsheet.traceback, "print_exc"):
            self.sheet.sync_once()
        self.assertEqual([entry[0] for entry in self.log], ["create", "mark", "create", "mark"])


class Stop(BaseException):
    pass


class HealthAlertTest(unittest.TestCase):
    def test_alerts_once_per_outage_and_reports_recovery(self):
        sheet = bare_sheet()
        outcomes = [TimeoutError("down")] * 4 + [None, None, TimeoutError("blip"), None]

        def sync_once():
            outcome = outcomes.pop(0)
            if outcome:
                raise outcome

        def sleep(_):
            if not outcomes:
                raise Stop

        sheet.sync_once = sync_once
        with (
            mock.patch.object(Spreadsheet, "sleep", sleep),
            mock.patch.object(Spreadsheet.traceback, "print_exc"),
            self.assertRaises(Stop),
        ):
            sheet.spreadsheet_to_calendar()
        calls = [call[0] for call in sheet.notifier.method_calls]
        # One alert at the 3rd failed pass, one recovery; the later single blip stays quiet
        self.assertEqual(calls, ["sync_failed", "sync_recovered"])


if __name__ == "__main__":
    unittest.main()
