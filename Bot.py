import telebot
from Parser import Parser
from Calendar import Calendar

class Bot:
    def __init__(self):
        with open('bot_token', 'r') as secret:
            self.token = secret.read()
        with open('telegram_ids', 'r') as f:
            self.ids = f.read()
        self.bot = telebot.TeleBot(self.token)

    def bot_func(self):
        @self.bot.message_handler(commands=['start'])
        def start(message):
            if str(message.from_user.id) in self.ids:
                self.bot.send_message(message.chat.id,
                                 text="Привет! Я бот для автоматизации гугл календаря!".format(
                                     message.from_user))
            else:
                print(message.from_user.id)
                self.bot.reply_to(message, "Этот бот не предназначен для общего пользования. " +
                             "Пожалуйста, напишите своего и пользуйтесь")

        @self.bot.message_handler(content_types=['text'])
        def get_text_messages(message):
            if str(message.from_user.id) in self.ids:
                if "outcinema.ru/rent" in message.text:
                    try:
                        parser = Parser(message.text)
                        calendar = Calendar(parser.parse())
                        self.bot.reply_to(message, calendar.create_event())
                    except Exception:
                        self.bot.reply_to(message, "Чет сломалось, я хз(")
                else:
                    self.bot.reply_to(message,
                                 "Это блин не заявка на аренду")
                    pass
            else:
                print(message.from_user.id)
                self.bot.reply_to(message, "Этот бот не предназначен для общего пользования. " +
                             "Пожалуйста, напишите своего и пользуйтесь")

        self.bot.polling(none_stop=True, interval=0)
