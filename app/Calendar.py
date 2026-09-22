import datetime
import hashlib

import Dates
import Income
from GoogleApi import GoogleApi, read_secret
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from Parser import Parser

UNTREATED = " (не обработана)"
SOURCE = "calendarbot"


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
            note = "Аренда пересекается с другими событиями"
            result_dict["comment"] = ", ".join(filter(None, [result_dict["comment"], note]))
            result_dict["description"] = Parser.description(result_dict)
        private = {"source": SOURCE, "summ": result_dict["summ"]}
        if sheet_row:
            private["sheet_row"] = str(sheet_row)
        body = {
            "id": self.event_id(result_dict),
            "summary": result_dict.get("name", "") + UNTREATED,
            "description": result_dict["description"],
            "start": {"dateTime": Dates.rfc3339(start), "timeZone": "Europe/Moscow"},
            "end": {"dateTime": Dates.rfc3339(end), "timeZone": "Europe/Moscow"},
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
        if not Income.is_untreated(event):
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

    def set_event_summ(self, event_id, summ):
        body = {"extendedProperties": {"private": {"summ": str(summ)}}}
        return (
            self.service()
            .events()
            .patch(calendarId=self.CALENDAR_ID, eventId=event_id, body=body)
            .execute(num_retries=3)
        )

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
