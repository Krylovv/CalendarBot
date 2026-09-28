import contextlib
import datetime
import itertools
import re
import time
import traceback

import Dates
import Income
import Report
import Robokassa
import Tariffs
import telebot
from Calendar import OVERLAP_NOTE, Calendar, EventExists
from googleapiclient.errors import HttpError
from Parser import Parser, parse_manual_rent
from Spreadsheet import Spreadsheets
from telebot import types

DENIED = (
    "Этот бот не предназначен для общего пользования. "
    + "Пожалуйста, напишите своего и пользуйтесь"
)
FAILED = "Тут какая-то ошибка"

# Telegram command menu; /about must describe every entry (checked in tests/test_bot.py)
COMMANDS = [
    ("next_week_rents", "Посмотреть аренды на следующую неделю"),
    ("untreated_rents", "Посмотреть необработанные аренды"),
    ("find_rent", "Найти аренду по дате, чтобы изменить или отменить"),
    ("add_rent", "Добавить аренду вручную"),
    ("monthly_income", "Доход за месяц"),
    ("monthly_report", "Собрать отчёт за месяц в таблицу"),
    ("tariffs", "Посмотреть и изменить тарифы"),
    ("about", "Что умеет бот"),
]

ABOUT = """Что умеет бот

📋 Команды
/next_week_rents — аренды на следующую неделю (пн–вс) и отдельно неоплаченные
/untreated_rents — необработанные аренды на ближайшие полгода, у каждой кнопки ✅ Подтвердить, ❌ Отменить и ✏️ Изменить. Если уведомление потерялось, все ожидающие аренды можно найти здесь
/find_rent — аренды за указанный день с теми же кнопками, в том числе подтверждённые
/add_rent — добавить аренду без сайта одной строкой: «25.10 19:30 3 Иван @ivan 5» (дата, время, часы, имя, телеграм и число людей — последние два можно пропустить). Бот покажет сумму и пересечения и создаст событие после подтверждения
/monthly_income — доход за выбранный месяц: записанные суммы плюс оценка по тарифам для событий без суммы
/monthly_report — собрать отчёт за выбранный месяц на новом листе таблицы заявок. Если лист уже есть, бот предложит собрать его заново
/tariffs — посмотреть и изменить тарифы
/about — эта справка

🔄 Автоматически
• Каждые 30 секунд бот проверяет таблицу заявок. Новая заявка становится событием «(не обработана)» в календаре, а в колонке P появляется TRUE.
• О каждой новой аренде бот пишет сюда: время, сумма, пересечения с другими событиями и выход за рабочие часы (10:00–23:00). Кнопки: ✅ Подтвердить — копирует аренду в публичный календарь (только имя и время, без описания), убирает «(не обработана)» и дописывает в описание строку «public: yes»; ❌ Отменить — удаляет событие из обоих календарей; ✏️ Изменить — перенести на другую дату и время или поменять стоимость (например, для скидки).
• При переносе бот показывает новое время, пересечения и сумму и ждёт подтверждения. Публичная копия переносится тоже. Сумма по тарифу пересчитывается, а изменённая вручную остаётся прежней. Строка в таблице заявок не меняется.
• Каждый четверг в 10:00 бот присылает аренды на следующую неделю, отдельно — неоплаченные: не подтверждённые или со счётом, который ждёт оплаты.
• В последний день месяца в 21:00 бот создаёт в таблице заявок лист «Месяц год» (имя, дата, сумма, комментарий, 20%, итог). В него попадают подтверждённые аренды (со строкой «public: yes» в описании) и события, созданные вручную: для них сумма по тарифам и комментарий «Не автоматизированная аренда». Готовый лист бот не перезаписывает.
• 💳 Счёт (если подключена Robokassa и у аренды есть сумма) — бот выставляет счёт на сумму аренды на 7 дней и присылает сообщение со ссылкой: перешлите его арендатору. Повторное нажатие присылает ту же ссылку. После оплаты бот сам подтверждает бронь (как ✅, с копией в публичном календаре) и сообщает «💰 Оплачено» (проверяет раз в 5 минут). При отмене аренды или изменении суммы неоплаченный счёт отменяется.
• Если строку не удалось разобрать, в колонке P появится «ОШИБКА: …» и придёт сообщение. Исправьте строку и очистите ячейку — бот попробует снова.
• Повторная заявка на ту же аренду не создаёт второе событие.
• Если связь с Google пропала дольше чем на полторы минуты, бот предупредит и сообщит, когда всё восстановится.

🔗 Заявки с сайта
Перешлите сюда сообщение заявки с outcinema.ru/rent — бот сразу создаст событие.

💰 Как считается сумма
Тариф зависит от дня: будни (пн–чт), пятница или выходные. У каждого есть цена за час до и после часа смены тарифа. Время считается по минутам: аренда 17:30–19:30 при смене в 18:00 — это 30 минут по первой цене и полтора часа по второй."""

MESSAGE_LIMIT = 4096
# One card per booking in /untreated_rents; more than ~10 messages at once risks
# Telegram's flood limit (429), so the rest come on the next request
UNTREATED_CARDS = 10
CALLBACK_LIMIT = 64
# A Telegram username as people type it: "@name", "name", "t.me/name" or "https://t.me/name".
# Tenants often give a phone or a misspelt name instead; then there is no "write" button
TG_USERNAME = re.compile(r"^(?:(?:https?://)?t\.me/|@)?([A-Za-z][A-Za-z0-9_]{4,31})/?$")


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


def tg_username(value):
    match = TG_USERNAME.match((value or "").strip())
    return match.group(1) if match else None


def tariff_breakdown(start, end):
    # "1,5 ч × 4 000 + 2 ч × 4 500"
    return " + ".join(
        f"{round(hours, 2):g} ч × {Income.money(price)}".replace(".", ",")
        for hours, price in Parser.summ_parts(start, end)
    )


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
        description = Income.strip_public_tag(event.get("description"))
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


def move_preview(event, start, end, conflicts):
    fields = description_fields(event)
    name = Income.strip_untreated(Income.title(event))
    people = fields.get("people") and fields["people"] + " чел."
    lines = ["📅 Перенести аренду?", " · ".join(filter(None, [name, fields.get("tg"), people]))]
    bounds = Dates.event_bounds(event)
    lines.append(f"Было: {Dates.format_span(*bounds)} ({Dates.format_hours(*bounds)})")
    lines.append(f"Станет: {Dates.format_span(start, end)} ({Dates.format_hours(start, end)})")
    summ, new_summ = Income.recorded_summ(event), Income.summ_after_move(event, start, end)
    if summ is not None and new_summ != summ:
        lines.append(
            f"Сумма по тарифу: {Income.money(summ)} → {Income.money(new_summ)} ₽ "
            f"({tariff_breakdown(start, end)})"
        )
    elif summ is not None:
        lines.append(f"Сумма: {Income.money(summ)} ₽")
        estimate = Parser.get_summ(start, end)
        if estimate != summ:
            lines.append(
                f"Сумма изменена вручную и не пересчитается (по тарифу {Income.money(estimate)} ₽)"
            )
    for other in conflicts:
        lines.append(
            f"⚠️ Пересекается: {Dates.format_span(*Dates.event_bounds(other))} {Income.title(other)}"
        )
    note = Parser.check_working_hours(start, end)
    if note:
        lines.append("⚠️ " + note)
    if start < Dates.now():
        lines.append("⚠️ Это время уже прошло")
    if Income.is_published(event):
        lines.append("Публичная копия тоже будет перенесена")
    return "\n".join(lines)


def new_rent_preview(result, start, end, conflicts):
    people = result["people"] and result["people"] + " чел."
    lines = [
        "🆕 Добавить аренду?",
        " · ".join(filter(None, [result["name"], result["tg"], people])),
        f"{Dates.format_span(start, end)} ({Dates.format_hours(start, end)})",
        f"Сумма по тарифу: {Income.money(int(result['summ']))} ₽ ({tariff_breakdown(start, end)})",
    ]
    for other in conflicts:
        lines.append(
            f"⚠️ Пересекается: {Dates.format_span(*Dates.event_bounds(other))} {Income.title(other)}"
        )
    if result["comment"]:
        lines.append("⚠️ " + result["comment"])
    if start < Dates.now():
        lines.append("⚠️ Это время уже прошло")
    return "\n".join(lines)


def report_callback(data):
    # "rep:m:2026-09" pick, "rep:y:2026" year, "rep:r:2026-09" rebuild; buttons sent before the
    # picker existed carry only "rep:2026-09" and meant rebuild
    parts = data.split(":")
    if len(parts) == 2:
        return "r", parts[1]
    return parts[1], parts[2]


def report_text(year, month, title, totals):
    count, total, share = totals
    return (
        f"📊 Отчёт за {Dates.MONTHS[month - 1]} {year} готов — лист «{title}» в таблице заявок\n"
        f"{Income.rents(count)} · {Income.money(total)} ₽ · "
        f"{Report.SHARE_PERCENT}% — {Income.money(share)} ₽"
    )


INVOICE_STATUSES = {
    Robokassa.NOT_PAID: "не оплачен",
    Robokassa.PAID: "оплачен",
    Robokassa.EXPIRED: "истёк",
    Robokassa.CANCELLED: "отменён",
}


def invoice_summ(invoice):
    return "?" if invoice["summ"] is None else Income.money(invoice["summ"])


def invoice_expires(invoice):
    try:
        return f"{Dates.parse_api_time(invoice['expires']):%d.%m %H:%M}"
    except ValueError:
        return "?"


def invoice_line(event):
    invoice = Income.invoice(event)
    if invoice is None:
        return None
    test = " (тест)" if invoice["test"] else ""
    status = INVOICE_STATUSES.get(invoice["status"], invoice["status"])
    number = f" №{invoice['number']}" if invoice["number"] else ""
    line = f"💳 Счёт{number}{test} на {invoice_summ(invoice)} ₽: {status}"
    if invoice["status"] == Robokassa.NOT_PAID:
        line += f" (до {invoice_expires(invoice)})"
    return line


def invoice_message(event):
    # Made to be forwarded to the tenant as is: no internal details. Test mode is marked on
    # the booking card instead
    invoice = Income.invoice(event)
    text = f"По стоимости у вас получится {invoice_summ(invoice)} ₽\nПредоплата: {invoice['url']}"
    bounds = Dates.event_bounds(event)
    return f"Аренда {Dates.format_span(*bounds)}\n{text}" if bounds else text


def unpaid_line(event):
    bounds = Dates.event_bounds(event)
    when = Dates.format_span(*bounds) if bounds else format_event(event).splitlines()[0]
    parts = [Income.strip_untreated(Income.title(event))]
    summ = Income.recorded_summ(event)
    if summ is not None:
        parts.append(Income.money(summ) + " ₽")
    invoice = Income.invoice(event)
    if invoice is None:
        parts.append("счёт не выставлен")
    elif invoice["status"] == Robokassa.NOT_PAID:
        parts.append(f"счёт до {invoice_expires(invoice)}")
    else:
        parts.append("счёт " + INVOICE_STATUSES.get(invoice["status"], invoice["status"]))
    return f"• {when} " + " · ".join(parts)


def next_week_text(start, events):
    last_day = start + datetime.timedelta(days=6)
    header = f"Аренды на следующую неделю ({start:%d.%m}–{last_day:%d.%m})"
    if not events:
        return header + ": нет"
    text = f"{header}: {len(events)}\n\n" + "\n\n".join(format_event(event) for event in events)
    unpaid = [event for event in events if Income.is_unpaid(event)]
    if unpaid:
        text += f"\n\n💳 Не оплачены ({len(unpaid)}):\n" + "\n".join(map(unpaid_line, unpaid))
    else:
        text += "\n\n💳 Неоплаченных нет"
    return text


def booking_card(event, conflicts=()):
    fields = description_fields(event)
    name = Income.strip_untreated(Income.title(event))
    people = fields.get("people") and fields["people"] + " чел."
    lines = [" · ".join(filter(None, [name, fields.get("tg"), people]))]
    bounds = Dates.event_bounds(event)
    if bounds:
        lines.append(f"{Dates.format_span(*bounds)} ({Dates.format_hours(*bounds)})")
    summ = Income.recorded_summ(event)
    if summ is not None:
        line = f"Сумма: {Income.money(summ)} ₽"
        # A sum set by hand (a discount) has no breakdown
        if bounds and summ and summ == Parser.get_summ(*bounds):
            line += f" ({tariff_breakdown(*bounds)})"
        lines.append(line)
    invoice = invoice_line(event)
    if invoice:
        lines.append(invoice)
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
        # Moves waiting for confirmation: token -> (event_id, start, end, booking card message)
        self.moves = {}
        self.move_tokens = itertools.count()
        # Manual bookings waiting for confirmation: token -> Parser.booking result
        self.new_rents = {}

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
        edits = [button("✏️ Изменить", self.event_callback("bk:ed", event["id"]))]
        invoice = Income.invoice(event)
        if (
            Robokassa.configured()
            and Income.recorded_summ(event)
            and Dates.event_bounds(event)
            and not (invoice and invoice["status"] == Robokassa.PAID)
        ):
            edits.append(button("💳 Счёт", self.event_callback("bk:iv", event["id"])))
        markup.row(*edits)
        links = []
        if event.get("htmlLink"):
            links.append(types.InlineKeyboardButton("Открыть в календаре", url=event["htmlLink"]))
        username = tg_username(description_fields(event).get("tg"))
        if username:
            links.append(types.InlineKeyboardButton("✉️ Написать", url=f"https://t.me/{username}"))
        if links:
            markup.row(*links)
        return markup

    def next_week_markup(self, events):
        # A button per unpaid rent: opens its booking card with the usual actions
        unpaid = [event for event in events if Income.is_unpaid(event)]
        if not unpaid:
            return None
        markup = types.InlineKeyboardMarkup()
        # Telegram allows up to 100 buttons per message
        for event in unpaid[:90]:
            bounds = Dates.event_bounds(event)
            when = f"{Dates.format_day(bounds[0])} {bounds[0]:%H:%M}" if bounds else ""
            label = " · ".join(filter(None, [Income.strip_untreated(Income.title(event)), when]))
            markup.add(button(label[:60], self.event_callback("bk:card", event["id"])))
        return markup

    def month_picker(self, year, prefix="inc"):
        markup = types.InlineKeyboardMarkup(row_width=3)
        today = Dates.today()
        months = []
        for month in range(1, 13):
            label = Dates.MONTHS_SHORT[month - 1]
            if (year, month) == (today.year, today.month):
                label = "• " + label
            months.append(button(label, f"{prefix}:m:{year}-{month:02d}"))
        markup.add(*months)
        markup.row(
            button(f"« {year - 1}", f"{prefix}:y:{year - 1}"),
            button(f"{year + 1} »", f"{prefix}:y:{year + 1}"),
        )
        return markup

    def send_income_report(self, chat_id, year, month):
        recorded, estimated = Income.split_month(Calendar().get_events_for_month(year, month))
        self.send_long(chat_id, Income.format_report(year, month, recorded, estimated))

    def send_report(self, chat_id, year, month, replace=False):
        title, totals = Spreadsheets().build_report(year, month, replace)
        if totals is None:
            markup = types.InlineKeyboardMarkup()
            markup.add(button("🔄 Собрать заново", f"rep:r:{year}-{month:02d}"))
            self.bot.send_message(
                chat_id,
                f"Лист «{title}» уже есть. Собрать заново? Правки на листе пропадут",
                reply_markup=markup,
            )
            return
        self.bot.send_message(
            chat_id,
            report_text(year, month, title, totals)
            + "\n\nАвтоматический отчёт в конце месяца этот лист не перезапишет: "
            "если он тестовый, удалите его или соберите заново командой /monthly_report",
        )

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

    def monthly_report(self, year, month, title, totals):
        self.notify_admins(report_text(year, month, title, totals))

    def report_exists(self, title):
        self.notify_admins(
            f"📊 Лист «{title}» уже есть, автоматический отчёт его не перезаписал. "
            "Собрать заново: /monthly_report"
        )

    def report_failed(self, year, month, error):
        self.notify_admins(
            f"⚠️ Не удалось создать отчёт за {Dates.MONTHS[month - 1]} {year}: "
            f"{describe_error(error)}\nБот повторяет попытки каждые 30 секунд."
        )

    def weekly_rents(self, start, events):
        self.notify_admins("📅 " + next_week_text(start, events), self.next_week_markup(events))

    def weekly_rents_failed(self, error):
        self.notify_admins(
            f"⚠️ Не удалось собрать аренды на следующую неделю: {describe_error(error)}\n"
            "Бот повторяет попытки каждые 30 секунд."
        )

    def invoice_paid(self, event):
        self.notify_admins(
            f"💰 Оплачено: {invoice_summ(Income.invoice(event))} ₽, "
            "бронь подтверждена и добавлена в публичный календарь\n" + booking_card(event),
            self.booking_markup(event),
        )

    def invoice_expired(self, event):
        self.notify_admins(
            f"⌛ Счёт на {invoice_summ(Income.invoice(event))} ₽ истёк неоплаченным\n"
            + booking_card(event),
            self.booking_markup(event),
        )

    def invoice_check_failed(self, error):
        self.notify_admins(
            f"⚠️ Не удалось проверить оплату счетов: {describe_error(error)}\n"
            "Бот повторяет попытки каждые 5 минут и не сообщит о проблеме повторно, "
            "пока проверка не пройдёт успешно."
        )

    # --- invoices

    def close_invoice(self, calendar, event):
        # -> (event, status) for an unpaid invoice; a payment found on the way is announced
        event, status = calendar.close_invoice(event)
        if status == Robokassa.PAID:
            self.invoice_paid(event)
        return event, status

    def issue_invoice(self, call, calendar, event):
        summ = Income.recorded_summ(event)
        if not summ:
            return "Сначала укажите стоимость"
        invoice = Income.invoice(event)
        if invoice and invoice["status"] == Robokassa.PAID:
            return "Счёт уже оплачен"
        if invoice and invoice["status"] == Robokassa.NOT_PAID:
            if invoice["summ"] == summ:
                # A repeated tap resends the link instead of making a second invoice,
                # unless the invoice was paid or expired since the last check
                event, status = calendar.refresh_invoice(event)
                if status is None:
                    self.bot.send_message(call.message.chat.id, invoice_message(event))
                    return "Счёт уже выставлен"
            else:
                event, status = self.close_invoice(calendar, event)
            if status == Robokassa.PAID:
                if invoice["summ"] == summ:
                    self.invoice_paid(event)
                return "Счёт уже оплачен"
        created = Robokassa.create_invoice(
            summ, Robokassa.invoice_description(*Dates.event_bounds(event))
        )
        try:
            event = calendar.set_invoice(event["id"], created)
        except Exception:
            # Unsaved, the invoice would be neither tracked nor shown: don't leave it payable
            with contextlib.suppress(Exception):
                Robokassa.deactivate(created["id"], created["test"])
            raise
        who = call.from_user.first_name or "без имени"
        self.append_status(
            call.message,
            f"💳 Счёт на {Income.money(summ)} ₽ выставлен ({who})",
            self.booking_markup(event),
        )
        self.bot.send_message(call.message.chat.id, invoice_message(event))
        return "Счёт выставлен"

    def invoice_after_summ_change(self, calendar, event):
        # -> (event, note or None). An unpaid invoice for the old sum is cancelled
        invoice = Income.invoice(event)
        summ = Income.recorded_summ(event)
        if invoice is None or invoice["summ"] == summ:
            return event, None
        if invoice["status"] == Robokassa.NOT_PAID:
            try:
                event, status = self.close_invoice(calendar, event)
            except Exception:
                traceback.print_exc()
                return event, (
                    "⚠️ Сумма изменилась, но старый счёт отменить не удалось. "
                    "Нажмите «💳 Счёт», чтобы выставить новый"
                )
            if status != Robokassa.PAID:
                return event, "💳 Сумма изменилась, старый счёт отменён: выставьте новый"
        if Income.invoice(event)["status"] == Robokassa.PAID:
            return event, (
                f"⚠️ Счёт на {invoice_summ(invoice)} ₽ уже оплачен, а сумма теперь "
                f"{Income.money(summ or 0)} ₽: разницу учтите вручную"
            )
        return event, None

    # --- booking buttons

    def edit_markup(self, event_id):
        markup = types.InlineKeyboardMarkup()
        markup.row(
            button("📅 Дата и время", self.event_callback("bk:mv", event_id)),
            button("💰 Стоимость", self.event_callback("bk:pr", event_id)),
        )
        markup.add(button("« Назад", self.event_callback("bk:keep", event_id)))
        return markup

    def delete_markup(self, event_id):
        markup = types.InlineKeyboardMarkup()
        markup.row(
            button("🗑 Да, удалить", self.event_callback("bk:rmy", event_id)),
            button("Нет", self.event_callback("bk:keep", event_id)),
        )
        return markup

    def append_status(self, message, note, reply_markup=None):
        # Adds an outcome line to the booking card; a repeated tap must not fail on "not modified"
        text = getattr(message, "text", None)
        if not text:
            # Telegram sends an "inaccessible message" without text for cards the bot can no
            # longer edit; the action itself is done, the toast reports it
            return
        if not text.endswith(note):
            text += "\n\n" + note
        try:
            self.bot.edit_message_text(
                text, message.chat.id, message.message_id, reply_markup=reply_markup
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
        if action == "card":
            # From a list: the card comes as a new message, the list stays as is
            event = Calendar().find_event(event_id)
            if event is None:
                return "Событие уже удалено"
            self.bot.send_message(
                chat_id, booking_card(event), reply_markup=self.booking_markup(event)
            )
            return None
        if action == "rm":
            # Deleting is irreversible: ask first
            self.bot.edit_message_reply_markup(
                chat_id, message_id, reply_markup=self.delete_markup(event_id)
            )
            return None
        if action == "ed":
            self.bot.edit_message_reply_markup(
                chat_id, message_id, reply_markup=self.edit_markup(event_id)
            )
            return None
        calendar = Calendar()
        event = calendar.find_event(event_id)
        if event is None:
            self.append_status(call.message, "Событие уже удалено из календаря")
            return "Событие уже удалено"
        if action == "ok":
            event, changed = calendar.confirm_event(event_id)
            if not changed:
                self.bot.edit_message_reply_markup(
                    chat_id, message_id, reply_markup=self.booking_markup(event)
                )
                return "Уже подтверждено"
            self.append_status(
                call.message,
                f"✅ Подтверждено, добавлено в публичный календарь ({who})",
                self.booking_markup(event),
            )
            return "Подтверждено"
        if action == "keep":
            self.bot.edit_message_reply_markup(
                chat_id, message_id, reply_markup=self.booking_markup(event)
            )
            return None
        if action == "rmy":
            invoice = Income.invoice(event)
            if invoice and invoice["status"] == Robokassa.NOT_PAID:
                # The tenant must not be able to pay for a cancelled booking
                event, status = self.close_invoice(calendar, event)
                if status == Robokassa.PAID:
                    self.append_status(
                        call.message,
                        "💰 Счёт только что оплачен. Если всё равно удалить, "
                        "деньги нужно вернуть вручную через Robokassa",
                        self.delete_markup(event_id),
                    )
                    return "Счёт оплачен"
            calendar.delete_event(event_id)
            note = f"❌ Отменено, событие удалено ({who})"
            invoice = Income.invoice(event)
            if invoice and invoice["status"] == Robokassa.PAID:
                note += "\n⚠️ Счёт был оплачен: деньги возвращаются вручную через Robokassa"
            self.append_status(call.message, note)
            return "Событие удалено"
        bounds = Dates.event_bounds(event)
        if not bounds:
            return "Событие на весь день изменить нельзя"
        if action == "iv":
            return self.issue_invoice(call, calendar, event)
        name = Income.strip_untreated(Income.title(event))
        if action == "mv":
            self.ask(
                chat_id,
                f"📅 Перенос: {name}, {Dates.format_span(*bounds)} ({Dates.format_hours(*bounds)})\n"
                "Отправьте новую дату и время начала, например «25.10 19:30». "
                "Длительность останется прежней; чтобы изменить её, добавьте часы: «25.10 19:30 3».\n"
                "Любая команда — отмена",
                self.receive_move,
                event_id,
                call.message,
            )
            return None
        if action == "pr":
            summ, estimate = Income.recorded_summ(event), Parser.get_summ(*bounds)
            now = "не записана" if summ is None else Income.money(summ) + " ₽"
            self.ask(
                chat_id,
                f"💰 Стоимость: {name}, {Dates.format_span(*bounds)}\n"
                f"Сейчас: {now} · по тарифу: {Income.money(estimate)} ₽\n"
                "Отправьте новую сумму в рублях, «+» — сумма по тарифу, "
                "«0» — бесплатно (в доход и отчёт не войдёт). Любая команда — отмена",
                self.receive_price,
                event_id,
                estimate,
                call.message,
            )
            return None
        return None

    # --- editing a booking: replies to the prompts above

    def receive_move(self, message, event_id, card):
        if not self.allowed(message.from_user):
            self.bot.reply_to(message, DENIED)
            return
        text = (message.text or "").strip()
        if not text or text.startswith("/"):
            self.bot.reply_to(message, "Перенос отменён")
            return
        retry = "Нажмите «📅 Дата и время» ещё раз"
        try:
            start, hours = Dates.parse_move(text, Dates.today())
        except ValueError:
            self.bot.reply_to(
                message, f"Не понял дату, нужно «25.10 19:30» или «25.10 19:30 3». {retry}"
            )
            return
        if hours is not None and not 0 < hours <= Income.MAX_RENT_HOURS:
            self.bot.reply_to(
                message, f"Длительность — от 0 до {Income.MAX_RENT_HOURS} часов. {retry}"
            )
            return
        try:
            calendar = Calendar()
            event = calendar.find_event(event_id)
            bounds = event and Dates.event_bounds(event)
            if not bounds:
                self.bot.reply_to(message, "Событие уже удалено из календаря")
                return
            duration = bounds[1] - bounds[0] if hours is None else datetime.timedelta(hours=hours)
            end = start + duration
            conflicts = calendar.find_conflicts(event_id, start, end)
            token = str(next(self.move_tokens))
            self.moves[token] = (event_id, start, end, card)
            markup = types.InlineKeyboardMarkup()
            markup.row(
                button("✅ Перенести", f"mv:ok:{token}"), button("Не переносить", f"mv:no:{token}")
            )
            self.bot.reply_to(
                message, move_preview(event, start, end, conflicts), reply_markup=markup
            )
        except Exception:
            traceback.print_exc()
            self.bot.reply_to(message, FAILED)

    def handle_move_action(self, call):
        _, action, token = call.data.split(":", 2)
        # Popped first, so a double tap can't move twice
        move = self.moves.pop(token, None)
        if move is None:
            return "Кнопка устарела"
        chat_id, message_id = call.message.chat.id, call.message.message_id
        if action == "no":
            self.append_status(call.message, "Перенос отменён")
            return None
        event_id, start, end, card = move
        calendar = Calendar()
        if calendar.find_event(event_id) is None:
            self.bot.edit_message_reply_markup(chat_id, message_id)
            return "Событие уже удалено"
        event, conflicts = calendar.move_event(event_id, start, end)
        event, note = self.invoice_after_summ_change(calendar, event)
        who = call.from_user.first_name or "без имени"
        self.bot.edit_message_text(
            f"📅 Перенесено ({who})\n"
            + booking_card(event, conflicts)
            + (f"\n\n{note}" if note else ""),
            chat_id,
            message_id,
            reply_markup=self.booking_markup(event),
        )
        # The old card keeps working, but its time is stale now
        with contextlib.suppress(Exception):
            self.append_status(card, f"📅 Перенесено на {Dates.format_span(start, end)} ({who})")
        return "Перенесено"

    def receive_price(self, message, event_id, estimate, card):
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
            self.bot.reply_to(message, "Некорректная сумма. Нажмите «💰 Стоимость» ещё раз")
            return
        try:
            calendar = Calendar()
            if calendar.find_event(event_id) is None:
                self.bot.reply_to(message, "Событие уже удалено из календаря")
                return
            event = calendar.set_event_summ(event_id, value)
            event, note = self.invoice_after_summ_change(calendar, event)
            saved = "бесплатно" if value == 0 else Income.money(value) + " ₽"
            who = message.from_user.first_name or "без имени"
            self.bot.reply_to(
                message,
                f"💰 Стоимость изменена: {saved} ({who})\n"
                + booking_card(event)
                + (f"\n\n{note}" if note else ""),
                reply_markup=self.booking_markup(event),
            )
            with contextlib.suppress(Exception):
                self.append_status(card, f"💰 Стоимость изменена: {saved} ({who})")
        except Exception:
            traceback.print_exc()
            self.bot.reply_to(message, FAILED)

    # --- adding a booking by hand

    def receive_new_rent(self, message, text=None):
        if not self.allowed(message.from_user):
            self.bot.reply_to(message, DENIED)
            return
        text = (message.text or "").strip() if text is None else text
        if not text or text.startswith("/"):
            self.bot.reply_to(message, "Добавление отменено")
            return
        try:
            start, hours, name, tg, people = parse_manual_rent(text, Dates.today())
        except ValueError:
            self.bot.reply_to(
                message,
                "Не понял. Нужно «25.10 19:30 3 Иван @ivan 5»: дата, время, часы и имя, "
                "телеграм и число людей можно пропустить. /add_rent",
            )
            return
        if not 0 < hours <= Income.MAX_RENT_HOURS:
            self.bot.reply_to(
                message, f"Длительность — от 0 до {Income.MAX_RENT_HOURS} часов. /add_rent"
            )
            return
        try:
            end = start + datetime.timedelta(hours=hours)
            result = Parser.booking({"name": name, "tg": tg, "people": people}, start, end)
            conflicts = Calendar().find_overlaps(start, end)
            token = str(next(self.move_tokens))
            self.new_rents[token] = result
            markup = types.InlineKeyboardMarkup()
            markup.row(
                button("✅ Создать", f"add:ok:{token}"), button("Не создавать", f"add:no:{token}")
            )
            self.bot.reply_to(
                message, new_rent_preview(result, start, end, conflicts), reply_markup=markup
            )
        except Exception:
            traceback.print_exc()
            self.bot.reply_to(message, FAILED)

    def handle_new_rent_action(self, call):
        _, action, token = call.data.split(":", 2)
        # Popped first, so a double tap can't create twice
        result = self.new_rents.pop(token, None)
        if result is None:
            return "Кнопка устарела"
        if action == "no":
            self.append_status(call.message, "Не добавлено")
            return None
        chat_id, message_id = call.message.chat.id, call.message.message_id
        calendar = Calendar()
        try:
            event, conflicts = calendar.create_event(result)
            header = f"🆕 Добавлено ({call.from_user.first_name or 'без имени'})"
        except EventExists as exists:
            event, conflicts = calendar.find_event(exists.event_id), []
            if event is None:
                self.bot.edit_message_text(
                    "Эта аренда уже создавалась и была отменена", chat_id, message_id
                )
                return None
            header = "Эта аренда уже есть в календаре"
        self.bot.edit_message_text(
            header + "\n" + booking_card(event, conflicts),
            chat_id,
            message_id,
            reply_markup=self.booking_markup(event),
        )
        return "Добавлено"

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
                self.send_long(
                    message.chat.id, next_week_text(start, events), self.next_week_markup(events)
                )
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
                shown = events[:UNTREATED_CARDS]
                header = f"Необработанные аренды: {len(events)}"
                if len(events) > len(shown):
                    header += (
                        f"\nПоказаны ближайшие {len(shown)}. "
                        "Подтвердите или отмените их и запросите список снова"
                    )
                self.bot.send_message(message.chat.id, header)
                # The same cards as new-booking notifications, so every pending booking
                # can be confirmed or cancelled from here even if its notification was lost
                for event in shown:
                    self.bot.send_message(
                        message.chat.id,
                        booking_card(event),
                        reply_markup=self.booking_markup(event),
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
            except Exception:
                traceback.print_exc()
                self.bot.send_message(chat_id, FAILED)

        @self.bot.message_handler(commands=["monthly_report"])
        def monthly_report(message):
            if not self.allowed(message.from_user):
                self.bot.reply_to(message, DENIED)
                return
            year = Dates.today().year
            self.bot.send_message(
                message.chat.id,
                f"За какой месяц собрать отчёт? ({year})",
                reply_markup=self.month_picker(year, "rep"),
            )

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("rep:"))
        def report_menu(call):
            self.answer(call)
            if not self.allowed(call.from_user):
                return
            chat_id = call.message.chat.id
            try:
                action, value = report_callback(call.data)
                if action == "y":
                    year = int(value)
                    self.bot.edit_message_text(
                        f"За какой месяц собрать отчёт? ({year})",
                        chat_id,
                        call.message.message_id,
                        reply_markup=self.month_picker(year, "rep"),
                    )
                    return
                year, month = map(int, value.split("-"))
                today = Dates.today()
                if (year, month) > (today.year, today.month):
                    self.bot.send_message(chat_id, "Этот месяц ещё не начался")
                elif action == "m":
                    self.send_report(chat_id, year, month)
                elif action == "r":
                    # Drop the button first, so a double tap can't rebuild the sheet twice
                    self.bot.edit_message_reply_markup(chat_id, call.message.message_id)
                    self.send_report(chat_id, year, month, replace=True)
            except Exception:
                traceback.print_exc()
                self.bot.send_message(chat_id, FAILED)

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

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("mv:"))
        def move_action(call):
            if not self.allowed(call.from_user):
                self.answer(call)
                return
            try:
                toast = self.handle_move_action(call)
            except Exception:
                traceback.print_exc()
                toast = FAILED
            self.answer(call, toast)

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith("add:"))
        def new_rent_action(call):
            if not self.allowed(call.from_user):
                self.answer(call)
                return
            try:
                toast = self.handle_new_rent_action(call)
            except Exception:
                traceback.print_exc()
                toast = FAILED
            self.answer(call, toast)

        @self.bot.message_handler(commands=["add_rent"])
        def add_rent(message):
            if not self.allowed(message.from_user):
                self.bot.reply_to(message, DENIED)
                return
            # "/add_rent 25.10 19:30 3 Иван" works in one message too
            text = (message.text or "").partition(" ")[2].strip()
            if text:
                self.receive_new_rent(message, text)
                return
            self.ask(
                message.chat.id,
                "Отправьте аренду одной строкой: «25.10 19:30 3 Иван Петров @ivan 5» — дата, "
                "время, часы, имя, телеграм и число людей (последние два можно пропустить). "
                "Любая команда — отмена",
                self.receive_new_rent,
            )

        @self.bot.message_handler(commands=["find_rent"])
        def find_rent(message):
            if not self.allowed(message.from_user):
                self.bot.reply_to(message, DENIED)
                return
            self.ask(
                message.chat.id,
                "За какой день показать аренды? Например «25.10». Любая команда — отмена",
                show_day_rents,
            )

        def show_day_rents(message):
            if not self.allowed(message.from_user):
                self.bot.reply_to(message, DENIED)
                return
            text = (message.text or "").strip()
            if not text or text.startswith("/"):
                self.bot.reply_to(message, "Поиск отменён")
                return
            try:
                day = Dates.parse_day(text, Dates.today())
            except ValueError:
                self.bot.reply_to(
                    message, "Не понял дату, нужно «25.10» или «25.10.2026». /find_rent"
                )
                return
            try:
                start = Dates.start_of(day)
                events = [
                    event
                    for event in Calendar().find_overlaps(start, start + datetime.timedelta(days=1))
                    if start <= Dates.event_bounds(event)[0]
                ]
                if not events:
                    self.bot.reply_to(message, f"{Dates.format_day(day)}: аренд нет")
                    return
                self.bot.reply_to(message, f"{Dates.format_day(day)}: {Income.rents(len(events))}")
                for event in events[:UNTREATED_CARDS]:
                    self.bot.send_message(
                        message.chat.id,
                        booking_card(event),
                        reply_markup=self.booking_markup(event),
                    )
            except Exception:
                traceback.print_exc()
                self.bot.reply_to(message, FAILED)

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
