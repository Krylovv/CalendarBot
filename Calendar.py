import datetime
import os.path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


class Calendar:
    def __init__(self):
        self.creds = None
        if os.path.exists("token.json"):
            self.creds = Credentials.from_authorized_user_file("token.json", self.SCOPES)
        # If there are no (valid) credentials available, let the user log in.
        if not self.creds or not self.creds.valid:
            if self.creds and self.creds.expired and self.creds.refresh_token:
                self.creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    # Записанные credentials, по которым мы получаем токен
                    "desktop_creds.json", self.SCOPES
                )
                self.creds = flow.run_local_server(port=0)
            with open("token.json", "w") as token:
                token.write(self.creds.to_json())
    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def create_event(self, result_dict):
        try:
            service = build("calendar", "v3", credentials=self.creds)
            event = {
                "summary": result_dict['name'] + " (не обработана)",
                "description": result_dict['Input'] + '\n' + result_dict['people'] +
                               ' человек ' + '\n' + 'Сумма ' + result_dict['summ'] +
                               'р' + '\n' + result_dict['comment'],
                "start": {
                    "dateTime": result_dict['date'] + 'T' + result_dict['time'] + '+03:00',
                    "timeZone": "Europe/Moscow"
                },
                "end": {
                    "dateTime": result_dict['end_date'] + 'T' + result_dict['end_time'] + '+03:00',
                    "timeZone": "Europe/Moscow"
                }
            }
            event = service.events().insert(calendarId="primary", body=event).execute()
            return event.get('htmlLink')
        except HttpError as error:
            print(f"An error occurred: {error}")

    # Функция получения аренд следующей недели
    def get_events_for_next_week(self):
        # Получаем дату следующего понедельника
        next_monday = datetime.date.today() + datetime.timedelta(days=(0 - datetime.date.today().weekday()) % 7)
        # Получаем дату следующего воскресенья
        next_sunday = next_monday + datetime.timedelta(days=(6 - next_monday.weekday()) % 7)
        try:
            service = build("calendar", "v3", credentials=self.creds)
            now = datetime.datetime.utcnow().isoformat() + "Z"
            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=str(next_monday) + 'T00:00:00Z',
                    timeMax=str(next_sunday) + 'T00:00:00Z',
                    maxResults=1000,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            events = events_result.get("items", [])
            if not events:
                print("No upcoming events found.")
                return

            # for event in events:
            #     start = event["start"].get("dateTime", event["start"].get("date"))
            #     print(start, event["summary"])
            return events
        except HttpError as error:
            print(f"An error occurred: {error}")


# Функция получения необработанных аренд имя + дата/время + ник тг + описание + сумма
# Посчитать аренды за месяц