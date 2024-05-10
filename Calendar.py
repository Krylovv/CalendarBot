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
            if self.event_intersects(result_dict):
                result_dict['comment'] += '\nАренда пересекается с другими событиями'
            event = {
                "summary": result_dict['name'] + " (не обработана)",
                "description": '#automated' + '\n' + result_dict['Input'] + '\n' + result_dict['people'] +
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

            return events
        except HttpError as error:
            print(f"An error occurred: {error}")

    def get_event_on_date(self, day):
        try:
            service = build("calendar", "v3", credentials=self.creds)
            now = datetime.datetime.utcnow().isoformat() + "Z"
            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=str(day) + 'T00:00:00Z',
                    timeMax=str(day) + 'T23:59:59Z',
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

            return events
        except HttpError as error:
            print(f"An error occurred: {error}")

    def event_intersects(self, event_dict):
        events = self.get_event_on_date(event_dict['date'])
        for event in events:

            start = datetime.datetime.strptime(event['start']['dateTime'][:-6], '%Y-%m-%dT%H:%M:%S')
            end = datetime.datetime.strptime(event['end']['dateTime'][:-6], '%Y-%m-%dT%H:%M:%S')
            new_event = datetime.datetime.strptime(event_dict['date'] + " " + event_dict['time'], '%Y-%m-%d %H:%M:%S')
            if start <= new_event <= end:
                return True
        return False

    def get_untreated_rents(self):
        # Получаем дату следующего понедельника
        start = datetime.date.today()
        # Получаем дату следующего воскресенья
        end = start + datetime.timedelta(days=180)
        try:
            service = build("calendar", "v3", credentials=self.creds)
            events_result = (
                service.events()
                .list(
                    calendarId="primary",
                    timeMin=str(start) + 'T00:00:00Z',
                    timeMax=str(end) + 'T00:00:00Z',
                    maxResults=1000,
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
            tmp_events = events_result.get("items", [])

            if not tmp_events:
                print("Необработанных аренд не найдено")
                return
            events = []
            for event in tmp_events:
                if "не обработана" in str(event["summary"]).lower():
                    events.append(event)
            return events
        except HttpError as error:
            print(f"An error occurred: {error}")


# В общем виде понять как менять записи https://developers.google.com/calendar/api/v3/reference/events/update
# Добавлять #automated или типо того для авто записей первой строкой
# Делать проверку на наличие #automated для будущей работы, не #automated не трогать
# Функция получения необработанных аренд имя + дата/время + ник тг + описание + сумма
# Функция перевода необработанных аренд в обработанные
# Посчитать аренды за месяц
# Продумать функционал скидки