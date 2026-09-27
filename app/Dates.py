import datetime
import re

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


DAY_FORMAT = r"(\d{1,2})\.(\d{1,2})(?:\.(\d{4}|\d{2}))?"
DAY_INPUT = re.compile(DAY_FORMAT + r"$")
# "25.10 19:30", "25.10.2026 19", optionally followed by hours: "25.10 19:30 2,5"
MOVE_INPUT = re.compile(DAY_FORMAT + r"\s+(\d{1,2})(?::(\d{2}))?(?:\s+(\d{1,2}(?:[.,]\d+)?))?$")


def day_from_parts(day, month, year, today):
    # Without a year, the date nearest to today: 05.01 typed in December is next January
    if year:
        return datetime.date(int(year) + (2000 if len(year) == 2 else 0), int(month), int(day))
    candidates = []
    for candidate_year in (today.year - 1, today.year, today.year + 1):
        # A missing 29.02 in some years is skipped, not an error
        try:
            candidates.append(datetime.date(candidate_year, int(month), int(day)))
        except ValueError:
            continue
    if not candidates:
        raise ValueError("no such date")
    return min(candidates, key=lambda candidate: abs(candidate - today))


def parse_day(text, today):
    # "25.10" or "25.10.2026" -> date; ValueError otherwise
    match = DAY_INPUT.match(text.strip())
    if not match:
        raise ValueError("expected DD.MM")
    return day_from_parts(*match.groups(), today)


def parse_move(text, today):
    # -> (start, hours); hours is None when not given. ValueError on anything else
    match = MOVE_INPUT.match(text.strip())
    if not match:
        raise ValueError("expected DD.MM HH:MM [hours]")
    day, month, year, hour, minute, hours = match.groups()
    start = start_of(day_from_parts(day, month, year, today)).replace(
        hour=int(hour), minute=int(minute or 0)
    )
    return start, float(hours.replace(",", ".")) if hours else None
