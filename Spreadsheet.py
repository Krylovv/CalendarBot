from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from GoogleApi import GoogleApi
from Parser import Parser
from Calendar import Calendar
from time import sleep


class Spreadsheets(GoogleApi):
    with open('secrets/spreadsheet_id', 'r') as secret:
        spreadsheet_id = secret.read()
    SPREADSHEET_ID = spreadsheet_id
    RANGE_NAME = "A1:P999"

    # Функция обращения к гугл таблице и получения списка событий 
    def get_applications(self) -> list:
        try:
            service = build("sheets", "v4", credentials=self.creds)
            sheet = service.spreadsheets()
            result = (
              sheet.values()
              .get(spreadsheetId=self.SPREADSHEET_ID, range=self.RANGE_NAME)
              .execute()
            )
            values = result.get("values", [])

            if not values:
                print("No data found.")
                return
            
            return values
        except HttpError as err:
            print(err)

    # Функция обновляет значения values в указанных ячейках range_name
    def update_values(self, range_name: str, value_input_option: str, values: list) -> list:
        try:
            service = build("sheets", "v4", credentials=self.creds)
            body = {"values": [values]}
            result = (
                service.spreadsheets()
                .values()
                .update(
                    spreadsheetId=self.SPREADSHEET_ID,
                    range=range_name,
                    valueInputOption=value_input_option,
                    body=body,
                )
                .execute()
            )
            return result
        except HttpError as error:
            print(f"An error occurred: {error}")
            return error

    # Функция возвращает список необработанных аренд
    def process_application(self) -> list:
        try:
            counter = 0
            untreated_events_list = []
            for application in self.get_applications():
                counter += 1
                if len(application) < 16:
                    txt = 'name: ' + application[0] + '\ntg: ' + application[1] + '\ndate: ' + application[4] + \
                          '\ntime: ' + application[5] + '\nhours: ' + application[6] + '\npeople: ' + application[7]
                    untreated_events_list.append(txt)
                    self.update_values('P' + str(counter), 'USER_ENTERED', ['True'])
            return untreated_events_list
        except HttpError as error:
            print(error)
            return error

    # Функция создает события в календаре для каждой необработанной аренды
    def spreadsheet_to_calendar(self):
        while True:
            try:
                events_list = self.process_application()
                if events_list:
                    calendar = Calendar()
                    for event in events_list:
                        parser = Parser(event)
                        calendar.create_event(parser.parse())
            except HttpError as error:
                print(error)
                return error
            sleep(30)
