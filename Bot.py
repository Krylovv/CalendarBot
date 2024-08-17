import telebot
from telebot import types
from Parser import Parser
from Calendar import Calendar
import time

class Bot:
    def __init__(self):
        with open('secrets/bot_token', 'r') as secret:
            self.token = secret.read()
        with open('secrets/telegram_ids', 'r') as f:
            self.ids = f.read()
        self.bot = telebot.TeleBot(self.token, threaded=False)

    def bot_func(self):
        @self.bot.message_handler(commands=['start'])
        def start(message):
            if str(message.from_user.id) in self.ids:
                c1 = types.BotCommand(command='next_week_rents', description='Посмотреть аренды на следующую неделю')
                c2 = types.BotCommand(command='untreated_rents', description='Посмотреть необработанные аренды')
                c3 = types.BotCommand(command='monthly_income', description='Получить сумму аренд за месяц')
                self.bot.set_my_commands([c1, c2, c3])
                self.bot.send_message(message.chat.id,
                                      text="Привет! Я бот для автоматизации гугл календаря!".format(
                                      message.from_user))
            else:
                self.bot.reply_to(message, "Этот бот не предназначен для общего пользования. " +
                                           "Пожалуйста, напишите своего и пользуйтесь")

        @self.bot.message_handler(commands=['next_week_rents'])
        def get_next_week_rents(message):
            if str(message.from_user.id) in self.ids:
                try:
                    calendar = Calendar()
                    events_list = calendar.get_events_for_next_week()
                    response = ''
                    if events_list:
                        for event in events_list:
                            date = event["start"].get("dateTime", event["start"].get("date"))[:-9].split('T')[0]
                            date = date.split('-')[2] + '-' + date.split('-')[1] + '-' + date.split('-')[0]
                            time_start = event["start"].get("dateTime", event["start"].get("date"))[:-9].split('T')[1]
                            time_end = event["end"].get("dateTime", event["end"].get("date"))[:-9].split('T')[1]

                            response += str(event["summary"] + '\n' +
                                             date + '\n' + time_start + ' - ' + time_end + '\n')
                            try:
                                response += str(event["description"].split('\n')[1] + '\n' +
                                                event["description"].split('\n')[3] + '\n')
                            except Exception:
                                pass
                            response += '\n'
                    else:
                        response = 'На следующей неделе аренд нет'
                    self.bot.reply_to(message, response)
                except Exception:
                    self.bot.reply_to(message, "Тут какая-то ошибка")
            else:
                self.bot.reply_to(message, "Этот бот не предназначен для общего пользования. " +
                                           "Пожалуйста, напишите своего и пользуйтесь")

        @self.bot.message_handler(commands=['untreated_rents'])
        def get_untreated_rents(message):
            if str(message.from_user.id) in self.ids:
                try:
                    calendar = Calendar()
                    events_list = calendar.get_untreated_rents()
                    response = ''
                    for event in events_list:
                        date = event["start"].get("dateTime", event["start"].get("date"))[:-9].split('T')[0]
                        date = date.split('-')[2] + '-' + date.split('-')[1] + '-' + date.split('-')[0]
                        time_start = event["start"].get("dateTime", event["start"].get("date"))[:-9].split('T')[1]
                        time_end = event["end"].get("dateTime", event["end"].get("date"))[:-9].split('T')[1]

                        response += str(event["summary"] + '\n' +
                                        date + '\n' + time_start + ' - ' + time_end + '\n')
                        try:
                            response += str(event["description"].split('\n')[1] + '\n' +
                                            event["description"].split('\n')[3] + '\n')
                        except Exception:
                            pass
                        response += '\n'
                    self.bot.reply_to(message, response)
                except Exception:
                    self.bot.reply_to(message, "Тут какая-то ошибка")
            else:
                self.bot.reply_to(message, "Этот бот не предназначен для общего пользования. " +
                                  "Пожалуйста, напишите своего и пользуйтесь")

        @self.bot.message_handler(commands=['monthly_income'])
        def starting_monthly_income_message(message):
            if str(message.from_user.id) in self.ids:
                try:
                    sent_msg = self.bot.reply_to(message, "Введите необходимый месяц в формате числа")
                    self.bot.register_next_step_handler(sent_msg, get_monthly_rent_income)
                except Exception:
                    self.bot.reply_to(message, "Тут какая-то ошибка")
            else:
                self.bot.reply_to(message, "Этот бот не предназначен для общего пользования. " +
                                  "Пожалуйста, напишите своего и пользуйтесь")

        def get_monthly_rent_income(message):
            if str(message.from_user.id) in self.ids:
                try:
                    month = int(message.text)
                    calendar = Calendar()
                    response = Parser.get_monthly_rent_income(calendar.get_rents_for_month(month))
                    self.bot.reply_to(message, response)
                except Exception:
                    self.bot.reply_to(message, "Тут какая-то ошибка")
            else:
                self.bot.reply_to(message, "Этот бот не предназначен для общего пользования. " +
                                  "Пожалуйста, напишите своего и пользуйтесь")

        @self.bot.message_handler(content_types=['text'])
        def get_text_messages(message):
            if str(message.from_user.id) in self.ids:
                if "outcinema.ru/rent" in message.text:
                    try:
                        parser = Parser(message.text)
                        calendar = Calendar()
                        self.bot.reply_to(message, f"<a href='{calendar.create_event(parser.parse())}'>"
                                                   f"Запись добавлена</a>",
                                          parse_mode='HTML')
                    except Exception:
                        self.bot.reply_to(message, "Чет сломалось, я хз(")
                else:
                    pass
            else:
                self.bot.reply_to(message, "Этот бот не предназначен для общего пользования. " +
                                           "Пожалуйста, напишите своего и пользуйтесь")

        while True:
            try:
                self.bot.polling(none_stop=True, interval=0)

            except Exception as e:
                print(e)
                time.sleep(15)
