import datetime

# All bookings are in Moscow time (UTC+3, no DST). Naive datetimes in this codebase mean MSK.
MSK = datetime.timezone(datetime.timedelta(hours=3), "MSK")

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]
MONTHS = [
    "январь",
    "февраль",
    "март",
    "апрель",
    "май",
    "июнь",
    "июль",
    "август",
    "сентябрь",
    "октябрь",
    "ноябрь",
    "декабрь",
]
MONTHS_SHORT = ["янв", "фев", "мар", "апр", "май", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]


def now():
    return datetime.datetime.now(MSK).replace(tzinfo=None)


def today():
    return datetime.datetime.now(MSK).date()


def start_of(day):
    return datetime.datetime.combine(day, datetime.time())


def rfc3339(value):
    # Calendar API wants an explicit offset; naive values are MSK
    if value.tzinfo is None:
        value = value.replace(tzinfo=MSK)
    return value.isoformat()


def parse_api_time(value):
    # "2026-09-22T19:00:00+03:00" (or "...Z") -> naive MSK datetime
    parsed = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(MSK).replace(tzinfo=None)


def event_bounds(event):
    # (start, end) as naive MSK datetimes, or None for all-day events
    if "dateTime" not in event.get("start", {}):
        return None
    return parse_api_time(event["start"]["dateTime"]), parse_api_time(event["end"]["dateTime"])


def next_week_range(day):
    # Monday..Monday of the week after the one containing `day` (on a Monday, that's next week)
    monday = start_of(day + datetime.timedelta(days=7 - day.weekday()))
    return monday, monday + datetime.timedelta(days=7)


def month_range(year, month):
    start = datetime.datetime(year, month, 1)
    end = datetime.datetime(year + month // 12, month % 12 + 1, 1)
    return start, end


def format_day(value):
    return f"{value:%d.%m} {WEEKDAYS[value.weekday()]}"


def format_span(start, end):
    return f"{format_day(start)} {start:%H:%M}–{end:%H:%M}"


def format_hours(start, end):
    hours = (end - start) / datetime.timedelta(hours=1)
    return f"{hours:g} ч".replace(".", ",")
