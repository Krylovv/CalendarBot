import datetime
import calendar
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from GoogleApi import GoogleApi


class Calendar(GoogleApi):
    def create_event(self, result_dict):
        try:
            service = build("calendar", "v3", credentials=self.creds)
            try:
                if self.event_intersects(result_dict):
                    result_dict['comment'] += ', Аренда пересекается с другими событиями'
            except:
                pass
            event = {
                "summary": result_dict['name'] + " (не обработана)",
                "description": result_dict['description'],
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

    def get_rents_for_month(self, month):
        current_year = datetime.datetime.now().year
        start = datetime.datetime.strptime('01-' + str(month) + '-' + str(current_year), '%d-%m-%Y').date()
        end = datetime.datetime.strptime(str(calendar.monthrange(current_year, month)[1]) + '-' +
                                         str(month) + '-' + str(current_year), '%d-%m-%Y').date()
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
            events = events_result.get("items", [])
            if not events:
                print("No upcoming events found.")
                return
            descriptions_list = []
            for event in events:
                if 'description' in event:
                    descriptions_list.append(event['description'])
            return descriptions_list
        except HttpError as error:
            print(f"An error occurred: {error}")


