import contextlib
import datetime
import time
import traceback

import Dates
import Income
import Tariffs
import telebot
from Calendar import UNTREATED, Calendar, EventExists
from googleapiclient.errors import HttpError
from Parser import Parser
from telebot import types

DENIED = (
    "Этот бот не предназначен для общего пользования. "
    + "Пожалуйста, напишите своего и пользуйтесь"
)
FAILED = "Тут какая-то ошибка"
OVERLAP_NOTE = "Аренда пересекается с другими событиями"

# Telegram command menu; /about must describe every entry (checked in tests/test_bot.py)
COMMANDS = [
    ("next_week_rents", "Посмотреть аренды на следующую неделю"),
    ("untreated_rents", "Посмотреть необработанные аренды"),
    ("monthly_income", "Доход за месяц"),
    ("tariffs", "Посмотреть и изменить тарифы"),
    ("about", "Что умеет бот"),
]

ABOUT = """Что умеет бот

📋 Команды
/next_week_rents — аренды на следующую неделю (пн–вс)
/untreated_rents — необработанные аренды на ближайшие полгода
/monthly_income — доход за выбранный месяц: записанные суммы плюс оценка по тарифам для событий без суммы. Кнопками ✏️ можно записать точную сумму или отметить, что это не аренда
/tariffs — посмотреть и изменить тарифы
/about — эта справка

🔄 Автоматически
• Каждые 30 секунд бот проверяет таблицу заявок. Новая заявка становится событием «(не обработана)» в календаре, а в колонке P появляется TRUE.
• О каждой новой аренде бот пишет сюда: время, сумма, пересечения с другими событиями и выход за рабочие часы (10:00–23:00). Кнопки: ✅ Подтвердить — убирает «(не обработана)», ❌ Отменить — удаляет событие из календаря.
• Если строку не удалось разобрать, в колонке P появится «ОШИБКА: …» и придёт сообщение. Исправьте строку и очистите ячейку — бот попробует снова.
• Повторная заявка на ту же аренду не создаёт второе событие.
• Если связь с Google пропала дольше чем на полторы минуты, бот предупредит и сообщит, когда всё восстановится.

🔗 Заявки с сайта
Перешлите сюда сообщение заявки с outcinema.ru/rent — бот сразу создаст событие.

💰 Как считается сумма
Тариф зависит от дня: будни (пн–чт), пятница или выходные. У каждого есть цена за час до и после часа смены тарифа. Время считается по минутам: аренда 17:30–19:30 при смене в 18:00 — это 30 минут по первой цене и полтора часа по второй."""
MESSAGE_LIMIT = 4096
CALLBACK_LIMIT = 64


def describe_error(error):
    # Short and secret-free: HttpError's full text includes request URLs with the sheet ID
    if isinstance(error, HttpError):
        return f"HTTP {error.resp.status}: {error.reason}"
    return f"{type(error).__name__}: {str(error)[:200]}"


def split_message(text, limit=MESSAGE_LIMIT):
    # Telegram rejects messages over 4096 characters; split between lines
    chunks, current = [], None
    for line in text.split("\n"):
        while len(line) > limit:
            if current is not None:
                chunks.append(current)
                current = None
            chunks.append(line[:limit])
            line = line[limit:]
        if current is None:
            current = line
        elif len(current) + 1 + len(line) <= limit:
            current += "\n" + line
        else:
            chunks.append(current)
            current = line
    if current is not None:
        chunks.append(current)
    return [chunk for chunk in chunks if chunk.strip()] or [text]


def button(text, data):
    return types.InlineKeyboardButton(text, callback_data=data)


def description_fields(event):
    fields = {}
    for line in (event.get("description") or "").splitlines():
        key, sep, value = line.partition(": ")
        if sep:
            fields[key.strip()] = value.strip()
    return fields


def format_event(event):
    bounds = Dates.event_bounds(event)
    if bounds:
        when = Dates.format_span(*bounds)
    else:
        when = Dates.format_day(datetime.date.fromisoformat(event["start"]["date"])) + " весь день"
    lines = [when, Income.title(event)]
    fields = description_fields(event)
    details = []
    if Income.is_bot_event(event):
        if fields.get("tg"):
            details.append(fields["tg"])
        if fields.get("people"):
            details.append(fields["people"] + " чел.")
    else:
        description = (event.get("description") or "").strip()
        if description:
            details.append(description.splitlines()[0][:100])
    summ = Income.recorded_summ(event)
    if summ:
        details.append(Income.money(summ) + " ₽")
    if details:
        lines.append(" · ".join(details))
    if Income.is_bot_event(event) and fields.get("comment"):
        lines.append("⚠️ " + fields["comment"])
    return "\n".join(lines)


def booking_card(event, conflicts=()):
    fields = description_fields(event)
    name = Income.title(event).replace(UNTREATED, "")
    people = fields.get("people") and fields["people"] + " чел."
    lines = [" · ".join(filter(None, [name, fields.get("tg"), people]))]
    bounds = Dates.event_bounds(event)
    if bounds:
        lines.append(f"{Dates.format_span(*bounds)} ({Dates.format_hours(*bounds)})")
    summ = Income.recorded_summ(event)
    if summ is not None:
        lines.append(f"Сумма: {Income.money(summ)} ₽")
    for other in conflicts:
        lines.append(
            f"⚠️ Пересекается: {Dates.format_span(*Dates.event_bounds(other))} {Income.title(other)}"
        )
    # Overlaps are listed above; show the remaining warnings (e.g. outside working hours)
    for note in (fields.get("comment") or "").split(", "):
        if note and note != OVERLAP_NOTE:
            lines.append("⚠️ " + note)
    return "\n".join(lines)


class Bot:
    def __init__(self):
        with open("./secrets/bot_token") as secret:
            self.token = secret.read().strip()
        with open("./secrets/telegram_ids") as f:
            # Exact IDs: a substring check on the raw file would also admit IDs contained in them
            self.ids = set(f.read().split())
        self.bot = telebot.TeleBot(self.token, threaded=False)
        # Short tokens for event IDs too long for Telegram's 64-byte callback data
        self.callback_ids = {}

    # --- helpers shared by handlers and sync notifications

    def allowed(self, user):
        return str(user.id) in self.ids

    def send_long(self, chat_id, text, reply_markup=None):
        chunks = split_message(text)
        for number, chunk in enumerate(chunks, 1):
            markup = reply_markup if number == len(chunks) else None
            self.bot.send_message(chat_id, chunk, reply_markup=markup)

    def answer(self, call, text=None):
        # Telegram rejects answers to queries older than ~15 seconds; nothing to do then
        with contextlib.suppress(Exception):
            self.bot.answer_callback_query(call.id, text)

    def ask(self, chat_id, text, callback, *args):
        # Only the latest prompt may consume the next message; otherwise one reply
        # would be applied to every prompt tapped before it
        self.bot.clear_step_handler_by_chat_id(chat_id)
        sent_msg = self.bot.send_message(chat_id, text)
        self.bot.register_next_step_handler(sent_msg, callback, *args)

    def event_callback(self, prefix, event_id):
        data = f"{prefix}:{event_id}"
        if len(data.encode()) <= CALLBACK_LIMIT:
            return data
        token = f"~{len(self.callback_ids)}"
        self.callback_ids[token] = event_id
        return f"{prefix}:{token}"

    def resolve_event_id(self, value):
        # Tokens don't survive a restart; plain IDs always work
        return self.callback_ids.get(value) if value.startswith("~") else value

    def booking_markup(self, event):
        markup = types.InlineKeyboardMarkup()
        actions = []
        if Income.is_untreated(event):
            actions.append(button("✅ Подтвердить", self.event_callback("bk:ok", event["id"])))
        actions.append(button("❌ Отменить", self.event_callback("bk:rm", event["id"])))
        markup.row(*actions)
        if event.get("htmlLink"):
            markup.add(types.InlineKeyboardButton("Открыть в календаре", url=event["htmlLink"]))
        return markup

    def month_picker(self, year):
        markup = types.InlineKeyboardMarkup(row_width=3)
        today = Dates.today()
        months = []
        for month in range(1, 13):
            label = Dates.MONTHS_SHORT[month - 1]
            if (year, month) == (today.year, today.month):
                label = "• " + label
            months.append(button(label, f"inc:m:{year}-{month:02d}"))
        markup.add(*months)
        markup.row(
            button(f"« {year - 1}", f"inc:y:{year - 1}"),
            button(f"{year + 1} »", f"inc:y:{year + 1}"),
        )
        return markup

    def send_income_report(self, chat_id, year, month):
        recorded, estimated = Income.split_month(Calendar().get_events_for_month(year, month))
        markup = None
        if estimated:
            markup = types.InlineKeyboardMarkup()
            # Telegram allows up to 100 buttons per message
            for event, _, bounds in estimated[:90]:
                label = f"✏️ {bounds[0]:%d.%m %H:%M} {Income.title(event)}"[:60]
                markup.add(button(label, self.event_callback("inc:s", event["id"])))
        self.send_long(chat_id, Income.format_report(year, month, recorded, estimated), markup)

    # --- notifications from the sync loop (see Spreadsheets.notify)

    def notify_admins(self, text, reply_markup=None):
        for user_id in self.ids:
            try:
                self.send_long(int(user_id), text, reply_markup)
            except Exception:
                # e.g. this user never opened the bot; keep notifying the others
                traceback.print_exc()

    def new_booking(self, event, conflicts, row):
        self.notify_admins(
            f"🆕 Новая аренда (строка {row})\n" + booking_card(event, conflicts),
            self.booking_markup(event),
        )

    def duplicate_booking(self, event, row):
        # event is None when the earlier event was deleted (booking cancelled)
        if event is None:
            self.notify_admins(
                f"🔁 Строка {row}: такая аренда уже создавалась и была отменена, повторно не создана"
            )
            return
        self.notify_admins(
            f"🔁 Строка {row}: такая аренда уже есть в календаре, повторно не создана\n"
            + booking_card(event),
            self.booking_markup(event),
        )

    def row_error(self, row, error):
        reasons = {
            IndexError: "в строке не хватает данных",
            KeyError: "нет обязательного поля",
            ValueError: "неверный формат даты, времени или часов",
        }
        reason = reasons.get(type(error), describe_error(error))
        self.notify_admins(
            f"⚠️ Строка {row} не обработана: {reason}.\n"
            f"Исправьте строку и очистите ячейку P{row} — бот попробует снова."
        )

    def sync_failed(self, error):
        self.notify_admins(
            f"⚠️ Синхронизация таблицы с календарём не работает: {describe_error(error)}\n"
            "Бот повторяет попытки каждые 30 секунд и сообщит, когда всё восстановится."
        )

    def sync_recovered(self):
        self.notify_admins("✅ Синхронизация таблицы с календарём восстановлена")

    # --- booking buttons

    def append_status(self, call, note, reply_markup=None):
        # Adds an outcome line to the booking card; a repeated tap must not fail on "not modified"
        text = getattr(call.message, "text", None)
        if not text:
            # Telegram sends an "inaccessible message" without text for cards the bot can no
            # longer edit; the action itself is done, the toast reports it
            return
        if not text.endswith(note):
            text += "\n\n" + note
        try:
            self.bot.edit_message_text(
                text, call.message.chat.id, call.message.message_id, reply_markup=reply_markup
            )
        except telebot.apihelper.ApiTelegramException as error:
            if "message is not modified" not in str(error):
                raise

    def handle_booking_action(self, call):
        _, action, token = call.data.split(":", 2)
        event_id = self.resolve_event_id(token)
        if event_id is None:
            return "Кнопка устарела"
        chat_id, message_id = call.message.chat.id, call.message.message_id
        who = call.from_user.first_name or "без имени"
        if action == "rm":
            # Deleting is irreversible: ask first
            markup = types.InlineKeyboardMarkup()
            markup.row(
                button("🗑 Да, удалить", self.event_callback("bk:rmy", event_id)),
                button("Нет", self.event_callback("bk:keep", event_id)),
            )
            self.bot.edit_message_reply_markup(chat_id, message_id, reply_markup=markup)
            return None
        calendar = Calendar()
        event = calendar.find_event(event_id)
        if event is None:
            self.append_status(call, "Событие уже удалено из календаря")
            return "Событие уже удалено"
        if action == "ok":
            event, changed = calendar.confirm_event(event_id)
            if not changed:
                self.bot.edit_message_reply_markup(
                    chat_id, message_id, reply_markup=self.booking_markup(event)
                )
                return "Уже подтверждено"
            self.append_status(call, f"✅ Подтверждено ({who})", self.booking_markup(event))
            return "Подтверждено"
        if action == "keep":
            self.bot.edit_message_reply_markup(
                chat_id, message_id, reply_markup=self.booking_markup(event)
            )
            return None
        if action == "rmy":
            calendar.delete_event(event_id)
            self.append_status(call, f"❌ Отменено, событие удалено ({who})")
            return "Событие удалено"
        return None

    def bot_func(self):
        @self.bot.message_handler(commands=["start"])
        def start(message):
            if self.allowed(message.from_user):
                self.bot.set_my_commands(
                    [types.BotCommand(command, description) for command, description in COMMANDS]
                )
                self.bot.send_message(
                    message.chat.id,
                    text="Привет! Я бот для автоматизации гугл календаря!\nЧто я умею: /about",
                )
            else:
                self.bot.reply_to(message, DENIED)

        @self.bot.message_handler(commands=["about"])
        def about(message):
            if self.allowed(message.from_user):
                self.send_long(message.chat.id, ABOUT)
            else:
                self.bot.reply_to(message, DENIED)

        @self.bot.message_handler(commands=["next_week_rents"])
        def get_next_week_rents(message):
            if not self.allowed(message.from_user):
                self.bot.reply_to(message, DENIED)
                return
            try:
                start, end = Dates.next_week_range(Dates.today())
                events = Calendar().list_events(start, end)
                if not events:
                    self.bot.reply_to(message, "На следующей неделе аренд нет")
                    return
                last_day = end - datetime.timedelta(days=1)
                header = f"Аренды на следующую неделю ({start:%d.%m}–{last_day:%d.%m}):"
                body = "\n\n".join(format_event(event) for event in events)
                self.send_long(message.chat.id, header + "\n\n" + body)
            except Exception:
                traceback.print_exc()
                self.bot.reply_to(message, FAILED)

        @self.bot.message_handler(commands=["untreated_rents"])
        def get_untreated_rents(message):
            if not self.allowed(message.from_user):
                self.bot.reply_to(message, DENIED)
                return
            try:
                events = Calendar().get_untreated_rents()
                if not events:
                    self.bot.reply_to(message, "Необработанных аренд нет")
                    return
                body = "\n\n".join(format_event(event) for event in events)
                self.send_long(
                    message.chat.id, f"Необработанные аренды ({len(events)}):\n\n" + body
                )
            except Exception:
                traceback.print_exc()
                self.bot.reply_to(message, FAILED)

        @self.bot.message_handler(commands=["monthly_income"])
        def starting_monthly_income_message(message):
            if not self.allowed(message.from_user):
                self.bot.reply_to(message, DENIED)
                return
            year = Dates.today().year
            self.bot.send_message(
                message.chat.id, f"Выберите месяц ({year}):", reply_markup=self.month_picker(year)
            )

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("inc:"))
        def income_menu(call):
            self.answer(call)
            if not self.allowed(call.from_user):
                return
            chat_id = call.message.chat.id
            try:
                _, action, value = call.data.split(":", 2)
                if action == "y":
                    year = int(value)
                    self.bot.edit_message_text(
                        f"Выберите месяц ({year}):",
                        chat_id,
                        call.message.message_id,
                        reply_markup=self.month_picker(year),
                    )
                elif action == "m":
                    year, month = map(int, value.split("-"))
                    self.send_income_report(chat_id, year, month)
                elif action == "s":
                    event_id = self.resolve_event_id(value)
                    if event_id is None:
                        self.bot.send_message(chat_id, "Кнопка устарела, запросите отчёт заново")
                        return
                    event = Calendar().find_event(event_id)
                    bounds = event and Dates.event_bounds(event)
                    if not bounds:
                        self.bot.send_message(chat_id, "Событие уже удалено из календаря")
                        return
                    estimate = Parser.get_summ(*bounds)
                    self.ask(
                        chat_id,
                        f"{Income.title(event)}, {Dates.format_span(*bounds)}\n"
                        f"Оценка по тарифам: {Income.money(estimate)} ₽\n"
                        "Отправьте сумму в рублях, «+» — записать оценку, «0» — это не аренда",
                        save_event_summ,
                        event_id,
                        estimate,
                        bounds[0],
                    )
            except Exception:
                traceback.print_exc()
                self.bot.send_message(chat_id, FAILED)

        def save_event_summ(message, event_id, estimate, start):
            if not self.allowed(message.from_user):
                self.bot.reply_to(message, DENIED)
                return
            text = (message.text or "").strip()
            if not text or text.startswith("/"):
                self.bot.reply_to(message, "Изменение отменено")
                return
            try:
                value = estimate if text == "+" else int(text.replace(" ", ""))
            except ValueError:
                value = -1
            if not 0 <= value <= 10000000:
                self.bot.reply_to(message, "Некорректная сумма, изменение отменено")
                return
            try:
                Calendar().set_event_summ(event_id, value)
                markup = types.InlineKeyboardMarkup()
                markup.add(
                    button(
                        f"🔄 Отчёт за {Dates.MONTHS[start.month - 1]} {start.year}",
                        f"inc:m:{start.year}-{start.month:02d}",
                    )
                )
                saved = "не аренда" if value == 0 else Income.money(value) + " ₽"
                self.bot.reply_to(message, f"Сохранено: {saved}", reply_markup=markup)
            except Exception:
                traceback.print_exc()
                self.bot.reply_to(message, FAILED)

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("bk:"))
        def booking_action(call):
            if not self.allowed(call.from_user):
                self.answer(call)
                return
            try:
                toast = self.handle_booking_action(call)
            except Exception:
                traceback.print_exc()
                toast = FAILED
            self.answer(call, toast)

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
                markup.add(button(title, "tariff:" + day))
            return markup

        def tariff_fields_markup(day):
            data = Tariffs.load()
            markup = types.InlineKeyboardMarkup()
            for field in ("price_before", "price_after", "splitter"):
                markup.add(button(tariff_field_title(data, day, field), f"tariff:{day}:{field}"))
            markup.add(button("« Назад", "tariff:back"))
            return markup

        @self.bot.message_handler(commands=["tariffs"])
        def show_tariffs(message):
            if not self.allowed(message.from_user):
                self.bot.reply_to(message, DENIED)
                return
            try:
                self.bot.send_message(
                    message.chat.id,
                    Tariffs.format_tariffs(Tariffs.load()),
                    reply_markup=tariff_days_markup(),
                )
            except Exception:
                self.bot.reply_to(message, FAILED)

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("tariff:"))
        def tariff_menu(call):
            self.answer(call)
            if not self.allowed(call.from_user):
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
                    self.ask(
                        chat_id,
                        f"{Tariffs.DAY_TYPES[day]}, {tariff_field_title(data, day, field).lower()}. "
                        + f"Сейчас: {Tariffs.get_value(data, day, field)}\n"
                        + f"Введите новое значение ({hint})",
                        save_tariff_value,
                        day,
                        field,
                    )
            except Exception:
                self.bot.send_message(chat_id, FAILED)

        def save_tariff_value(message, day, field):
            if not self.allowed(message.from_user):
                self.bot.reply_to(message, DENIED)
                return
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
                self.bot.reply_to(message, FAILED)

        @self.bot.message_handler(content_types=["text"])
        def get_text_messages(message):
            if not self.allowed(message.from_user):
                self.bot.reply_to(message, DENIED)
                return
            if "outcinema.ru/rent" not in message.text:
                return
            try:
                result = Parser(message.text).parse()
                calendar = Calendar()
                try:
                    event, conflicts = calendar.create_event(result)
                    header = "Запись добавлена"
                except EventExists as exists:
                    event, conflicts = calendar.find_event(exists.event_id), []
                    if event is None:
                        self.bot.reply_to(message, "Эта аренда уже создавалась и была отменена")
                        return
                    header = "Эта аренда уже есть в календаре"
                self.bot.reply_to(
                    message,
                    header + "\n" + booking_card(event, conflicts),
                    reply_markup=self.booking_markup(event),
                )
            except Exception:
                traceback.print_exc()
                self.bot.reply_to(message, "Чет сломалось, я хз(")

        while True:
            try:
                self.bot.polling(none_stop=True, interval=0)

            except Exception as e:
                print(e)
                time.sleep(15)
