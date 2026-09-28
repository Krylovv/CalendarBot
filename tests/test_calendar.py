import datetime
import re
import unittest
from unittest import mock

import httplib2
from googleapiclient.errors import HttpError
from support import timed_event, use_tariffs

import Robokassa
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


class MockedCalendar(unittest.TestCase):
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


class ConfirmDeleteTest(MockedCalendar):
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
        event = booking(summary="Иван")
        event["description"] += "public: yes\n"
        self.events.get.return_value.execute.return_value = event
        _, changed = self.calendar.confirm_event("cb1")
        self.assertFalse(changed)
        self.assertEqual(self.calls(), [("get", "tech")])

    def test_manual_booking_without_mark_is_published(self):
        # e.g. an event made by hand in the calendar and then paid
        manual = timed_event(START, END, summary="Анна", event_id="m1")
        self.events.get.return_value.execute.return_value = manual
        _, changed = self.calendar.confirm_event("m1")
        self.assertTrue(changed)
        self.assertEqual(self.calls(), [("get", "tech"), ("insert", "public"), ("patch", "tech")])
        self.assertEqual(self.events.patch.call_args.kwargs["body"]["description"], "public: yes\n")

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


class PriceTest(MockedCalendar):
    def test_price_updates_the_visible_line_too(self):
        self.events.get.return_value.execute.return_value = booking()
        self.calendar.set_event_summ("cb1", 15000)
        self.assertEqual(
            self.events.patch.call_args.kwargs["body"],
            {
                "extendedProperties": {"private": {"summ": "15000"}},
                "description": "type: automated\ntg: @ivan\npeople: 5\nsumm: 15000\n",
            },
        )

    def test_manual_description_is_left_alone(self):
        manual = timed_event(START, END, summary="Анна", description="@anna\nзвонила")
        self.events.get.return_value.execute.return_value = manual
        self.calendar.set_event_summ("e1", 9000)
        self.assertEqual(
            self.events.patch.call_args.kwargs["body"],
            {"extendedProperties": {"private": {"summ": "9000"}}},
        )


class MoveTest(MockedCalendar):
    # 23.09 Wed 19:30-23:30 (4 * 4500) -> 26.09 Sat 14:00-18:00 (2 * 4500 + 2 * 5000)
    NEW = datetime.datetime(2026, 9, 26, 14), datetime.datetime(2026, 9, 26, 18)

    def setUp(self):
        super().setUp()
        use_tariffs(self)
        self.calendar.find_overlaps = lambda start, end: [booking()]

    def test_confirmed_booking_moves_with_public_copy(self):
        event = booking(summary="Иван")
        event["description"] += "comment: Аренда пересекается с другими событиями\npublic: yes\n"
        event["extendedProperties"]["private"]["summ"] = "18000"
        self.events.get.return_value.execute.return_value = event
        _, conflicts = self.calendar.move_event("cb1", *self.NEW)
        self.assertEqual(conflicts, [])
        self.assertEqual(self.calls(), [("get", "tech"), ("patch", "public"), ("patch", "tech")])
        public, main = (call.kwargs for call in self.events.patch.call_args_list)
        self.assertEqual(public["eventId"], Calendar.public_event_id("cb1"))
        self.assertEqual(public["body"]["start"]["dateTime"], "2026-09-26T14:00:00+03:00")
        self.assertEqual(main["body"]["extendedProperties"], {"private": {"summ": "19000"}})
        self.assertIn("summ: 19000\ncomment: \npublic: yes\n", main["body"]["description"])

    def test_discount_is_kept(self):
        self.events.get.return_value.execute.return_value = booking()
        self.calendar.move_event("cb1", *self.NEW)
        self.assertEqual(self.calls(), [("get", "tech"), ("patch", "tech")])
        self.assertNotIn("extendedProperties", self.events.patch.call_args.kwargs["body"])


def invoiced(status="NotPaid"):
    event = booking(summary="Иван")
    event["extendedProperties"]["private"].update(
        invoice_id="inv1", invoice_status=status, invoice_summ="22000", invoice_test="1"
    )
    return event


class InvoiceTest(MockedCalendar):
    def setUp(self):
        super().setUp()
        self.events.patch.return_value.execute.side_effect = lambda **_: invoiced(
            self.events.patch.call_args.kwargs["body"]["extendedProperties"]["private"][
                "invoice_status"
            ]
        )
        self.calendar.confirm_event = mock.Mock()
        self.robokassa = {}
        for name in ("invoice_status", "deactivate"):
            patcher = mock.patch.object(Robokassa, name)
            self.robokassa[name] = patcher.start()
            self.addCleanup(patcher.stop)

    def test_invoice_is_saved_in_private_properties(self):
        self.events.patch.return_value.execute.side_effect = None
        self.calendar.set_invoice(
            "cb1",
            {
                "id": "inv1",
                "inv_id": 123285133,
                "url": "https://pay/inv1",
                "summ": 22000,
                "expires": datetime.datetime(2026, 10, 4, 12),
                "test": True,
            },
        )
        self.assertEqual(
            self.events.patch.call_args.kwargs["body"],
            {
                "extendedProperties": {
                    "private": {
                        "invoice_id": "inv1",
                        "invoice_number": "123285133",
                        "invoice_url": "https://pay/inv1",
                        "invoice_status": "NotPaid",
                        "invoice_summ": "22000",
                        "invoice_expires": "2026-10-04T12:00:00+03:00",
                        "invoice_test": "1",
                    }
                }
            },
        )

    def test_pending_invoices_are_filtered_by_status(self):
        self.events.list.return_value.execute.return_value = {
            "items": [invoiced(), dict(invoiced(), status="cancelled")]
        }
        self.assertEqual(len(self.calendar.pending_invoices()), 1)
        self.assertEqual(
            self.events.list.call_args.kwargs["privateExtendedProperty"], "invoice_status=NotPaid"
        )

    def test_refresh_saves_only_a_change(self):
        self.robokassa["invoice_status"].return_value = "NotPaid"
        self.assertEqual(self.calendar.refresh_invoice(invoiced())[1], None)
        self.events.patch.assert_not_called()
        self.robokassa["invoice_status"].return_value = "Paid"
        event, status = self.calendar.refresh_invoice(invoiced())
        self.assertEqual(
            (status, event["extendedProperties"]["private"]["invoice_status"]), ("Paid", "Paid")
        )

    def test_payment_confirms_booking_before_saving_status(self):
        self.robokassa["invoice_status"].return_value = "Paid"
        self.calendar.confirm_event.side_effect = TimeoutError("public calendar down")
        with self.assertRaises(TimeoutError):
            self.calendar.refresh_invoice(invoiced())
        # Still NotPaid in the calendar, so the next check retries
        self.events.patch.assert_not_called()
        self.calendar.confirm_event.side_effect = None
        self.calendar.refresh_invoice(invoiced())
        self.calendar.confirm_event.assert_called_with("cb1")
        self.events.patch.assert_called_once()

    def test_expired_invoice_does_not_confirm(self):
        self.robokassa["invoice_status"].return_value = "Expired"
        self.calendar.refresh_invoice(invoiced())
        self.calendar.confirm_event.assert_not_called()

    def test_close_deactivates_unpaid_invoice(self):
        self.robokassa["invoice_status"].return_value = "NotPaid"
        _, status = self.calendar.close_invoice(invoiced())
        self.assertEqual(status, Robokassa.CANCELLED)
        self.robokassa["deactivate"].assert_called_once_with("inv1", True)

    def test_test_invoice_after_going_live_is_cancelled_quietly(self):
        self.robokassa["invoice_status"].side_effect = Robokassa.ModeMismatch("mode")
        _, status = self.calendar.refresh_invoice(invoiced())
        self.assertEqual(status, Robokassa.CANCELLED)
        _, status = self.calendar.close_invoice(invoiced())
        self.assertEqual(status, Robokassa.CANCELLED)
        self.robokassa["deactivate"].assert_not_called()

    def test_close_keeps_a_paid_invoice(self):
        self.robokassa["invoice_status"].return_value = "Paid"
        _, status = self.calendar.close_invoice(invoiced())
        self.assertEqual(status, "Paid")
        self.robokassa["deactivate"].assert_not_called()


if __name__ == "__main__":
    unittest.main()
