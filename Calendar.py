import datetime
import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class Calendar:
    def __init__(self, result_dict):
        self.result_dict = result_dict
    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def create_event(self):
        creds = None
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", self.SCOPES)
        # If there are no (valid) credentials available, let the user log in.
        # if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "desktop_creds.json", self.SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())

        try:
            service = build("calendar", "v3", credentials=creds)
            event = {
                "summary": self.result_dict['name'],
                "description": self.result_dict['Input'] + '\n' + self.result_dict['people'] +
                               ' человек ' + '\n' + 'Сумма ' + self.result_dict['summ'] + 'р',
                "start": {
                    "dateTime": self.result_dict['date'] + 'T' + self.result_dict['time'] + '+03:00',
                    "timeZone": "Europe/Moscow"
                },
                "end": {
                    "dateTime": self.result_dict['date'] + 'T' + self.result_dict['endtime'] + '+03:00',
                    "timeZone": "Europe/Moscow"
                }
            }
            event = service.events().insert(calendarId="primary", body=event).execute()
            return f"Event created {event.get('htmlLink')}"
        except HttpError as error:
            print(f"An error occurred: {error}")

    def get_events(self):
        creds = None
        if os.path.exists("token.json"):
            creds = Credentials.from_authorized_user_file("token.json", self.SCOPES)
        # If there are no (valid) credentials available, let the user log in.
        # if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                "desktop_creds.json", self.SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as token:
            token.write(creds.to_json())

        try:
            service = build("calendar", "v3", credentials=creds)
            now = datetime.datetime.utcnow().isoformat() + "Z"
            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=now,
                    maxResults=10,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            events = events_result.get("items", [])
            print(events)
            if not events:
                print("No upcoming events found.")
                return

            # Prints the start and name of the next 10 events
            for event in events:
                start = event["start"].get("dateTime", event["start"].get("date"))
                print(start, event["summary"])

            return events

        except HttpError as error:
            print(f"An error occurred: {error}")

