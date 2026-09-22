import re
import unittest
from unittest import mock

import httplib2
from googleapiclient.errors import HttpError
from support import timed_event

from Calendar import Calendar

START, END = "2026-09-23T19:30:00+03:00", "2026-09-23T23:30:00+03:00"


def http_error(status):
    return HttpError(httplib2.Response({"status": status}), b"{}")


def booking(summary="Иван (не обработана)"):
    return timed_event(
        START,
        END,
        summary=summary,
        description="type: automated\ntg: @ivan\npeople: 5\nsumm: 22000\n",
        private={"source": "calendarbot", "summ": "22000"},
        event_id="cb1",
    )


class PublicCopyTest(unittest.TestCase):
    def test_body_has_name_and_time_only(self):
        body = Calendar.public_body(booking())
        self.assertEqual(
            body,
            {
                "id": Calendar.public_event_id("cb1"),
                "summary": "Иван",
                "start": {"dateTime": START},
                "end": {"dateTime": END},
            },
        )

    def test_id_is_stable_and_valid(self):
        event_id = Calendar.public_event_id("cb1")
        self.assertEqual(event_id, Calendar.public_event_id("cb1"))
        self.assertNotEqual(event_id, Calendar.public_event_id("cb2"))
        # Calendar IDs allow only a-v and 0-9
        self.assertRegex(event_id, re.compile(r"^[a-v0-9]{5,1024}$"))


class ConfirmDeleteTest(unittest.TestCase):
    def setUp(self):
        # Skip GoogleApi.__init__: no credentials, a mock in place of the API
        self.calendar = Calendar.__new__(Calendar)
        self.calendar.CALENDAR_ID = "tech"
        self.calendar.public_calendar_id = lambda: "public"
        api = mock.Mock()
        self.calendar.service = lambda: api
        self.events = api.events.return_value

    def calls(self):
        return [(name, kwargs["calendarId"]) for name, _, kwargs in self.events.method_calls]

    def test_confirm_publishes_then_tags(self):
        self.events.get.return_value.execute.return_value = booking()
        _, changed = self.calendar.confirm_event("cb1")
        self.assertTrue(changed)
        self.assertEqual(self.calls(), [("get", "tech"), ("insert", "public"), ("patch", "tech")])
        self.assertEqual(self.events.insert.call_args.kwargs["body"]["summary"], "Иван")
        self.assertEqual(
            self.events.patch.call_args.kwargs["body"],
            {
                "summary": "Иван",
                "description": "type: automated\ntg: @ivan\npeople: 5\nsumm: 22000\npublic: yes\n",
            },
        )

    def test_failed_publish_keeps_booking_untreated(self):
        self.events.get.return_value.execute.return_value = booking()
        self.events.insert.return_value.execute.side_effect = TimeoutError("network")
        with self.assertRaises(TimeoutError):
            self.calendar.confirm_event("cb1")
        self.events.patch.assert_not_called()

    def test_existing_copy_is_restored_not_duplicated(self):
        self.events.get.return_value.execute.return_value = booking()
        self.events.insert.return_value.execute.side_effect = http_error(409)
        self.calendar.confirm_event("cb1")
        self.assertEqual(
            self.calls(),
            [("get", "tech"), ("insert", "public"), ("patch", "public"), ("patch", "tech")],
        )
        restore = self.events.patch.call_args_list[0].kwargs
        self.assertEqual(restore["eventId"], Calendar.public_event_id("cb1"))
        self.assertEqual(restore["body"]["status"], "confirmed")
        self.assertNotIn("id", restore["body"])

    def test_confirmed_booking_is_left_alone(self):
        self.events.get.return_value.execute.return_value = booking(summary="Иван")
        _, changed = self.calendar.confirm_event("cb1")
        self.assertFalse(changed)
        self.assertEqual(self.calls(), [("get", "tech")])

    def test_delete_removes_public_copy_first(self):
        self.events.delete.return_value.execute.side_effect = [http_error(404), None]
        self.calendar.delete_event("cb1")
        self.assertEqual(self.calls(), [("delete", "public"), ("delete", "tech")])
        self.assertEqual(
            self.events.delete.call_args_list[0].kwargs["eventId"],
            Calendar.public_event_id("cb1"),
        )

    def test_delete_stops_if_public_calendar_fails(self):
        self.events.delete.return_value.execute.side_effect = http_error(500)
        with self.assertRaises(HttpError):
            self.calendar.delete_event("cb1")
        self.assertEqual(self.calls(), [("delete", "public")])


if __name__ == "__main__":
    unittest.main()
