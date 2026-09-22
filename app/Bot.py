import telebot
from telebot import types
from Parser import Parser
from Calendar import Calendar
import Tariffs
import time


class Bot:
    def __init__(self):
        with open("./secrets/bot_token", "r") as secret:
            self.token = secret.read()
        with open("./secrets/telegram_ids", "r") as f:
            self.ids = f.read()
        self.bot = telebot.TeleBot(self.token, threaded=False)

    def bot_func(self):
        @self.bot.message_handler(commands=["start"])
        def start(message):
            if str(message.from_user.id) in self.ids:
                c1 = types.BotCommand(
                    command="next_week_rents", description="Посмотреть аренды на следующую неделю"
                )
                c2 = types.BotCommand(
                    command="untreated_rents", description="Посмотреть необработанные аренды"
                )
                c3 = types.BotCommand(
                    command="monthly_income", description="Получить сумму аренд за месяц"
                )
                c4 = types.BotCommand(command="tariffs", description="Посмотреть и изменить тарифы")
                self.bot.set_my_commands([c1, c2, c3, c4])
                self.bot.send_message(
                    message.chat.id,
                    text="Привет! Я бот для автоматизации гугл календаря!".format(
                        message.from_user
                    ),
                )
            else:
                self.bot.reply_to(
                    message,
                    "Этот бот не предназначен для общего пользования. "
                    + "Пожалуйста, напишите своего и пользуйтесь",
                )

        @self.bot.message_handler(commands=["next_week_rents"])
        def get_next_week_rents(message):
            if str(message.from_user.id) in self.ids:
                try:
                    calendar = Calendar()
                    events_list = calendar.get_events_for_next_week()
                    response = ""
                    if events_list:
                        for event in events_list:
                            date = (
                                event["start"]
                                .get("dateTime", event["start"].get("date"))[:-9]
                                .split("T")[0]
                            )
                            date = (
                                date.split("-")[2]
                                + "-"
                                + date.split("-")[1]
                                + "-"
                                + date.split("-")[0]
                            )
                            time_start = (
                                event["start"]
                                .get("dateTime", event["start"].get("date"))[:-9]
                                .split("T")[1]
                            )
                            time_end = (
                                event["end"]
                                .get("dateTime", event["end"].get("date"))[:-9]
                                .split("T")[1]
                            )

                            response += str(
                                event["summary"]
                                + "\n"
                                + date
                                + "\n"
                                + time_start
                                + " - "
                                + time_end
                                + "\n"
                            )
                            try:
                                response += str(
                                    event["description"].split("\n")[1]
                                    + "\n"
                                    + event["description"].split("\n")[3]
                                    + "\n"
                                )
                            except Exception:
                                pass
                            response += "\n"
                    else:
                        response = "На следующей неделе аренд нет"
                    self.bot.reply_to(message, response)
                except Exception:
                    self.bot.reply_to(message, "Тут какая-то ошибка")
            else:
                self.bot.reply_to(
                    message,
                    "Этот бот не предназначен для общего пользования. "
                    + "Пожалуйста, напишите своего и пользуйтесь",
                )

        @self.bot.message_handler(commands=["untreated_rents"])
        def get_untreated_rents(message):
            if str(message.from_user.id) in self.ids:
                try:
                    calendar = Calendar()
                    events_list = calendar.get_untreated_rents()
                    response = ""
                    for event in events_list:
                        date = (
                            event["start"]
                            .get("dateTime", event["start"].get("date"))[:-9]
                            .split("T")[0]
                        )
                        date = (
                            date.split("-")[2] + "-" + date.split("-")[1] + "-" + date.split("-")[0]
                        )
                        time_start = (
                            event["start"]
                            .get("dateTime", event["start"].get("date"))[:-9]
                            .split("T")[1]
                        )
                        time_end = (
                            event["end"]
                            .get("dateTime", event["end"].get("date"))[:-9]
                            .split("T")[1]
                        )

                        response += str(
                            event["summary"]
                            + "\n"
                            + date
                            + "\n"
                            + time_start
                            + " - "
                            + time_end
                            + "\n"
                        )
                        try:
                            response += str(
                                event["description"].split("\n")[1]
                                + "\n"
                                + event["description"].split("\n")[3]
                                + "\n"
                            )
                        except Exception:
                            pass
                        response += "\n"
                    self.bot.reply_to(message, response)
                except Exception:
                    self.bot.reply_to(message, "Тут какая-то ошибка")
            else:
                self.bot.reply_to(
                    message,
                    "Этот бот не предназначен для общего пользования. "
                    + "Пожалуйста, напишите своего и пользуйтесь",
                )

        @self.bot.message_handler(commands=["monthly_income"])
        def starting_monthly_income_message(message):
            if str(message.from_user.id) in self.ids:
                try:
                    sent_msg = self.bot.reply_to(
                        message, "Введите необходимый месяц в формате числа"
                    )
                    self.bot.register_next_step_handler(sent_msg, get_monthly_rent_income)
                except Exception:
                    self.bot.reply_to(message, "Тут какая-то ошибка")
            else:
                self.bot.reply_to(
                    message,
                    "Этот бот не предназначен для общего пользования. "
                    + "Пожалуйста, напишите своего и пользуйтесь",
                )

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
                self.bot.reply_to(
                    message,
                    "Этот бот не предназначен для общего пользования. "
                    + "Пожалуйста, напишите своего и пользуйтесь",
                )

        def tariff_field_title(data, day, field):
            splitter = data[day]["splitter"]
            titles = {
                "price_before": f"Цена до {splitter}:00",
                "price_after": f"Цена с {splitter}:00",
                "splitter": "Час смены тарифа",
            }
            return titles[field]

        def tariff_days_markup():
            markup = types.InlineKeyboardMarkup()
            for day, title in Tariffs.DAY_TYPES.items():
                markup.add(types.InlineKeyboardButton(title, callback_data="tariff:" + day))
            return markup

        def tariff_fields_markup(day):
            data = Tariffs.load()
            markup = types.InlineKeyboardMarkup()
            for field in ("price_before", "price_after", "splitter"):
                markup.add(
                    types.InlineKeyboardButton(
                        tariff_field_title(data, day, field),
                        callback_data=f"tariff:{day}:{field}",
                    )
                )
            markup.add(types.InlineKeyboardButton("« Назад", callback_data="tariff:back"))
            return markup

        @self.bot.message_handler(commands=["tariffs"])
        def show_tariffs(message):
            if str(message.from_user.id) in self.ids:
                try:
                    self.bot.send_message(
                        message.chat.id,
                        Tariffs.format_tariffs(Tariffs.load()),
                        reply_markup=tariff_days_markup(),
                    )
                except Exception:
                    self.bot.reply_to(message, "Тут какая-то ошибка")
            else:
                self.bot.reply_to(
                    message,
                    "Этот бот не предназначен для общего пользования. "
                    + "Пожалуйста, напишите своего и пользуйтесь",
                )

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("tariff:"))
        def tariff_menu(call):
            self.bot.answer_callback_query(call.id)
            if str(call.from_user.id) not in self.ids:
                return
            chat_id = call.message.chat.id
            try:
                parts = call.data.split(":")
                if parts[1] == "back":
                    self.bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        reply_markup=tariff_days_markup(),
                    )
                elif len(parts) == 2 and parts[1] in Tariffs.DAY_TYPES:
                    self.bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=call.message.message_id,
                        reply_markup=tariff_fields_markup(parts[1]),
                    )
                elif (
                    len(parts) == 3 and parts[1] in Tariffs.DAY_TYPES and parts[2] in Tariffs.FIELDS
                ):
                    day, field = parts[1], parts[2]
                    data = Tariffs.load()
                    hint = "час от 0 до 24" if field == "splitter" else "рублей за час"
                    sent_msg = self.bot.send_message(
                        chat_id,
                        f"{Tariffs.DAY_TYPES[day]}, {tariff_field_title(data, day, field).lower()}. "
                        + f"Сейчас: {Tariffs.get_value(data, day, field)}\n"
                        + f"Введите новое значение ({hint})",
                    )
                    self.bot.register_next_step_handler(sent_msg, save_tariff_value, day, field)
            except Exception:
                self.bot.send_message(chat_id, "Тут какая-то ошибка")

        def save_tariff_value(message, day, field):
            if str(message.from_user.id) in self.ids:
                if not message.text or message.text.startswith("/"):
                    self.bot.reply_to(message, "Изменение отменено")
                    return
                try:
                    value = int(message.text.strip())
                except ValueError:
                    value = None
                low, high = (0, 24) if field == "splitter" else (1, 1000000)
                if value is None or not low <= value <= high:
                    self.bot.reply_to(
                        message,
                        "Некорректное значение, изменение отменено",
                        reply_markup=tariff_fields_markup(day),
                    )
                    return
                try:
                    data = Tariffs.update(day, field, value)
                    # Keep the menu open so several tariffs can be changed in a row
                    self.bot.reply_to(
                        message,
                        "Сохранено\n\n" + Tariffs.format_tariffs(data),
                        reply_markup=tariff_fields_markup(day),
                    )
                except Exception:
                    self.bot.reply_to(message, "Тут какая-то ошибка")
            else:
                self.bot.reply_to(
                    message,
                    "Этот бот не предназначен для общего пользования. "
                    + "Пожалуйста, напишите своего и пользуйтесь",
                )

        @self.bot.message_handler(content_types=["text"])
        def get_text_messages(message):
            if str(message.from_user.id) in self.ids:
                if "outcinema.ru/rent" in message.text:
                    try:
                        parser = Parser(message.text)
                        calendar = Calendar()
                        self.bot.reply_to(
                            message,
                            f"<a href='{calendar.create_event(parser.parse())}'>"
                            f"Запись добавлена</a>",
                            parse_mode="HTML",
                        )
                    except Exception:
                        self.bot.reply_to(message, "Чет сломалось, я хз(")
                else:
                    pass
            else:
                self.bot.reply_to(
                    message,
                    "Этот бот не предназначен для общего пользования. "
                    + "Пожалуйста, напишите своего и пользуйтесь",
                )

        while True:
            try:
                self.bot.polling(none_stop=True, interval=0)

            except Exception as e:
                print(e)
                time.sleep(15)
