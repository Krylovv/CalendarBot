import datetime
import hashlib

import Dates
import Income
import Robokassa
from GoogleApi import GoogleApi, read_secret
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from Parser import Parser

UNTREATED = " (не обработана)"
SOURCE = "calendarbot"
OVERLAP_NOTE = "Аренда пересекается с другими событиями"


class EventExists(Exception):
    def __init__(self, event_id):
        super().__init__(event_id)
        self.event_id = event_id


class Calendar(GoogleApi):
    def __init__(self):
        super().__init__()
        # Service accounts have their own empty "primary" calendar, so the target calendar
        # (shared with the service account) must be addressed explicitly.
        self.CALENDAR_ID = read_secret("calendar_id")

    def service(self):
        return build("calendar", "v3", credentials=self.creds)

    def public_calendar_id(self):
        # Read on use, so a missing file breaks only confirming and cancelling, not every command
        return read_secret("public_calendar_id")

    def list_events(self, start, end):
        # All events overlapping [start, end), following pagination
        service = self.service()
        events, page_token = [], None
        while True:
            result = (
                service.events()
                .list(
                    calendarId=self.CALENDAR_ID,
                    timeMin=Dates.rfc3339(start),
                    timeMax=Dates.rfc3339(end),
                    maxResults=2500,
                    singleEvents=True,
                    orderBy="startTime",
                    pageToken=page_token,
                )
                .execute(num_retries=3)
            )
            events += result.get("items", [])
            page_token = result.get("nextPageToken")
            if not page_token:
                return events

    @staticmethod
    def event_id(result_dict):
        # The same booking always maps to the same ID, so a retry can't create a duplicate.
        # Calendar IDs allow only a-v and 0-9; a hex digest fits.
        fields = ("name", "tg", "date", "time", "hours", "people")
        key = "|".join(str(result_dict.get(field, "")) for field in fields)
        return "cb" + hashlib.sha1(key.encode()).hexdigest()

    @staticmethod
    def public_event_id(event_id):
        # The public copy is found from its booking, so confirming twice can't duplicate it.
        # Not the booking's own ID: Google may merge events sharing an iCalUID.
        return "cbp" + hashlib.sha1(event_id.encode()).hexdigest()

    @staticmethod
    def public_body(event):
        # Name and time only: the public calendar must not show personal details
        return {
            "id": Calendar.public_event_id(event["id"]),
            "summary": Income.strip_untreated(Income.title(event)),
            "start": event["start"],
            "end": event["end"],
        }

    def publish_event(self, event):
        body = self.public_body(event)
        calendar_id = self.public_calendar_id()
        events = self.service().events()
        try:
            # No retries, as in create_event
            return events.insert(calendarId=calendar_id, body=body).execute()
        except HttpError as error:
            if error.resp.status != 409:
                raise
        # Published before (or deleted by hand, which keeps the ID taken): bring it back as is now
        update = {key: value for key, value in body.items() if key != "id"}
        update["status"] = "confirmed"
        return events.patch(calendarId=calendar_id, eventId=body["id"], body=update).execute(
            num_retries=3
        )

    @staticmethod
    def time_field(value):
        return {"dateTime": Dates.rfc3339(value), "timeZone": "Europe/Moscow"}

    def find_overlaps(self, start, end):
        # The API already returns only events overlapping [start, end); skip all-day markers
        return [event for event in self.list_events(start, end) if Dates.event_bounds(event)]

    def create_event(self, result_dict, sheet_row=None):
        start = datetime.datetime.fromisoformat(result_dict["date"] + "T" + result_dict["time"])
        end = datetime.datetime.fromisoformat(
            result_dict["end_date"] + "T" + result_dict["end_time"]
        )
        conflicts = self.find_overlaps(start, end)
        if conflicts:
            note = OVERLAP_NOTE
            result_dict["comment"] = ", ".join(filter(None, [result_dict["comment"], note]))
            result_dict["description"] = Parser.description(result_dict)
        private = {"source": SOURCE, "summ": result_dict["summ"]}
        if sheet_row:
            private["sheet_row"] = str(sheet_row)
        body = {
            "id": self.event_id(result_dict),
            "summary": result_dict.get("name", "") + UNTREATED,
            "description": result_dict["description"],
            "start": self.time_field(start),
            "end": self.time_field(end),
            "extendedProperties": {"private": private},
        }
        try:
            # No retries here: a retried insert that actually succeeded would look like a duplicate
            event = self.service().events().insert(calendarId=self.CALENDAR_ID, body=body).execute()
        except HttpError as error:
            if error.resp.status == 409:
                raise EventExists(body["id"]) from error
            raise
        return event, conflicts

    def get_event(self, event_id):
        return (
            self.service()
            .events()
            .get(calendarId=self.CALENDAR_ID, eventId=event_id)
            .execute(num_retries=3)
        )

    def find_event(self, event_id):
        # None if the event was deleted (the API answers 404/410 or status "cancelled")
        try:
            event = self.get_event(event_id)
        except HttpError as error:
            if error.resp.status in (404, 410):
                return None
            raise
        return None if event.get("status") == "cancelled" else event

    def confirm_event(self, event_id):
        # Returns (event, changed); confirming twice is harmless
        event = self.get_event(event_id)
        # A booking made by hand has no untreated mark but still needs publishing once paid
        if not Income.is_untreated(event) and Income.is_published(event):
            return event, False
        # Publish first: if that fails, the booking stays untreated and can be confirmed again
        self.publish_event(event)
        body = {
            "summary": Income.strip_untreated(event["summary"]),
            "description": Income.add_public_tag(event.get("description")),
        }
        event = (
            self.service()
            .events()
            .patch(calendarId=self.CALENDAR_ID, eventId=event_id, body=body)
            .execute(num_retries=3)
        )
        return event, True

    def delete_event(self, event_id):
        # The public copy first: if deleting the booking then fails, a retry finishes the job
        events = self.service().events()
        try:
            events.delete(
                calendarId=self.public_calendar_id(), eventId=self.public_event_id(event_id)
            ).execute(num_retries=3)
        except HttpError as error:
            # Unconfirmed bookings have no public copy
            if error.resp.status not in (404, 410):
                raise
        events.delete(calendarId=self.CALENDAR_ID, eventId=event_id).execute(num_retries=3)

    def find_conflicts(self, event_id, start, end):
        # Overlaps at a new time, without the booking itself
        return [event for event in self.find_overlaps(start, end) if event["id"] != event_id]

    def move_event(self, event_id, start, end):
        # -> (event, conflicts); moving to the same time again is harmless
        event = self.get_event(event_id)
        conflicts = self.find_conflicts(event_id, start, end)
        body = {"start": self.time_field(start), "end": self.time_field(end)}
        summ = Income.summ_after_move(event, start, end)
        if summ is not None and summ != Income.recorded_summ(event):
            body["extendedProperties"] = {"private": {"summ": str(summ)}}
        if Income.is_bot_event(event):
            # Warnings on the card must describe the new time, not the old one
            notes = [Parser.check_working_hours(start, end), conflicts and OVERLAP_NOTE]
            description = Income.set_description_field(
                event.get("description"), "comment", ", ".join(filter(None, notes))
            )
            if summ is not None:
                description = Income.set_description_field(description, "summ", summ)
            body["description"] = description
        events = self.service().events()
        if Income.is_published(event):
            # The public copy first, as in delete_event: a retry finishes the job
            try:
                events.patch(
                    calendarId=self.public_calendar_id(),
                    eventId=self.public_event_id(event_id),
                    body={"start": body["start"], "end": body["end"]},
                ).execute(num_retries=3)
            except HttpError as error:
                # Tagged by hand, without a copy made by the bot
                if error.resp.status not in (404, 410):
                    raise
        event = events.patch(calendarId=self.CALENDAR_ID, eventId=event_id, body=body).execute(
            num_retries=3
        )
        return event, conflicts

    def set_event_summ(self, event_id, summ):
        # The hidden field is what the bot counts; the "summ: N" line of a bot description is
        # what people see in the calendar, so it must follow. Other descriptions are left alone
        event = self.get_event(event_id)
        body = {"extendedProperties": {"private": {"summ": str(summ)}}}
        description = event.get("description") or ""
        updated = Income.set_description_field(description, "summ", summ)
        if updated != description:
            body["description"] = updated
        return (
            self.service()
            .events()
            .patch(calendarId=self.CALENDAR_ID, eventId=event_id, body=body)
            .execute(num_retries=3)
        )

    def patch_private(self, event_id, private):
        body = {"extendedProperties": {"private": private}}
        return (
            self.service()
            .events()
            .patch(calendarId=self.CALENDAR_ID, eventId=event_id, body=body)
            .execute(num_retries=3)
        )

    def set_invoice(self, event_id, invoice):
        # Replaces the booking's previous invoice, if any
        return self.patch_private(
            event_id,
            {
                "invoice_id": invoice["id"],
                "invoice_number": str(invoice["inv_id"]),
                "invoice_url": invoice["url"],
                "invoice_status": Robokassa.NOT_PAID,
                "invoice_summ": str(invoice["summ"]),
                "invoice_expires": Dates.rfc3339(invoice["expires"]),
                "invoice_test": "1" if invoice["test"] else "0",
            },
        )

    def set_invoice_status(self, event_id, status):
        return self.patch_private(event_id, {"invoice_status": status})

    def refresh_invoice(self, event):
        # -> (event, new status, or None if unchanged)
        invoice = Income.invoice(event)
        try:
            status = Robokassa.invoice_status(invoice["id"], invoice["test"])
        except Robokassa.ModeMismatch:
            # A test invoice left from before going live (or the reverse): it can't be checked
            # any more, and real money can't be paid by it
            status = Robokassa.CANCELLED
        if status == invoice["status"]:
            return event, None
        if status == Robokassa.PAID:
            # A paid booking is confirmed and goes to the public calendar. First: if that fails,
            # the invoice stays NotPaid here and the next check retries
            self.confirm_event(event["id"])
        return self.set_invoice_status(event["id"], status), status

    def close_invoice(self, event):
        # Stops an unpaid invoice from being paid -> (event, status). Checked first: an invoice
        # paid meanwhile comes back as Paid and stays so
        event, status = self.refresh_invoice(event)
        if status is not None:
            return event, status
        invoice = Income.invoice(event)
        Robokassa.deactivate(invoice["id"], invoice["test"])
        return self.set_invoice_status(event["id"], Robokassa.CANCELLED), Robokassa.CANCELLED

    def pending_invoices(self):
        # Bookings whose invoice may still be paid, at any date: payment can come after the rent
        service = self.service()
        events, page_token = [], None
        while True:
            result = (
                service.events()
                .list(
                    calendarId=self.CALENDAR_ID,
                    privateExtendedProperty=f"invoice_status={Robokassa.NOT_PAID}",
                    maxResults=2500,
                    singleEvents=True,
                    pageToken=page_token,
                )
                .execute(num_retries=3)
            )
            events += [
                event for event in result.get("items", []) if event.get("status") != "cancelled"
            ]
            page_token = result.get("nextPageToken")
            if not page_token:
                return events

    # Функция получения аренд следующей недели
    def get_events_for_next_week(self):
        return self.list_events(*Dates.next_week_range(Dates.today()))

    def get_untreated_rents(self):
        start = Dates.start_of(Dates.today())
        events = self.list_events(start, start + datetime.timedelta(days=180))
        return [event for event in events if Income.is_untreated(event)]

    def get_events_for_month(self, year, month):
        # Full month in Moscow time; an event belongs to the month it starts in
        start, end = Dates.month_range(year, month)
        events = []
        for event in self.list_events(start, end):
            bounds = Dates.event_bounds(event)
            if bounds and start <= bounds[0] < end:
                events.append(event)
        return events
