import datetime
import os.path
import telebot
from telebot import types

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# If modifying these scopes, delete the file token.json.
SCOPES = ["https://www.googleapis.com/auth/calendar"]
def bot_func():
    with open('bot_token', 'r') as secret:
        token = secret.read()
    bot = telebot.TeleBot(token)

    @bot.message_handler(commands=['start'])
    def start(message):
        markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
        btn1 = types.KeyboardButton("Следующая ➡️")
        markup.add(btn1)
        bot.send_message(message.chat.id,
                         text="Привет! Я бот для автоматизации гугл календаря!".format(
                             message.from_user), reply_markup=markup)

    @bot.message_handler(content_types=['text'])
    def get_text_messages(message):
        if "outcinema.ru/rent" in message.text:
            try:
                tmp = parse(message.text)
                calendar(tmp)
            except Exception:
                bot.reply_to(message, "Кажется, вопросы кончились...")
        else:
            pass
    bot.polling(none_stop=True, interval=0)


def parse(text):
    result_dict = {}
    message = ''
    required = ['date', 'time', 'hours', 'people', 'Input', 'name']
    for line in text.split('\n'):
        for item in required:
            if item + ':' in line:
                output = line.split(':')
                result_dict[output[0]] = output[1][1:]
    result_dict['date'] = result_dict['date'].split('-')[2] + '-' + result_dict['date'].split('-')[1] + '-' + result_dict['date'].split('-')[0]
    if ':' or '-' or ' ' not in result_dict['time']:
        end = int(result_dict['time']) + int(result_dict['hours'])
        result_dict['endtime'] = str(end)+':00:00'
        if end <= 23:
            pass
        else:
            print('Аренда выходит за рамки рабочего дня')
        result_dict['time'] = result_dict['time']+':00:00'
    return result_dict

def calendar(result_dict):
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    # If there are no (valid) credentials available, let the user log in.
    # if not creds or not creds.valid:
    #     if creds and creds.expired and creds.refresh_token:
    #         creds.refresh(Request())
    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            "desktop_creds.json", SCOPES
        )
        creds = flow.run_local_server(port=0)
    with open("token.json", "w") as token:
        token.write(creds.to_json())

    try:
        service = build("calendar", "v3", credentials=creds)
        now = datetime.datetime.utcnow().isoformat() + "Z"  # 'Z' indicates UTC time
        event = {
            "summary": result_dict['name'],
            "description": result_dict['Input'] + '\n' + result_dict['people'] + ' человек',
            # TODO посчитать сумму
            "start": {
                "dateTime": result_dict['date'] + 'T' + result_dict['time'] + '+03:00',
                "timeZone": "Europe/Moscow"
            },
            "end": {
                "dateTime": result_dict['date'] + 'T' + result_dict['endtime'] + '+03:00',
                "timeZone": "Europe/Moscow"
            }
        }
        event = service.events().insert(calendarId="primary", body=event).execute()
        print(f"Event created {event.get('htmlLink')}")
    except HttpError as error:
        print(f"An error occurred: {error}")


def main():
    bot_func()


if __name__ == "__main__":
    main()
