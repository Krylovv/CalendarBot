import datetime
import re

import Dates
from Parser import Parser

# Longer timed events (vacations, all-week holds) are not rentals
MAX_RENT_HOURS = 12


def private_props(event):
    return event.get("extendedProperties", {}).get("private", {})


def is_bot_event(event):
    return private_props(event).get("source") == "calendarbot" or "type: automated" in (
        event.get("description") or ""
    )


# The marker the bot appends to new events; any letter case, with or without brackets.
# Listing and confirming both use it, so a listed booking can always be confirmed.
UNTREATED_MARK = re.compile(r"\s*\(?не обработана\)?", re.IGNORECASE)


def is_untreated(event):
    return bool(UNTREATED_MARK.search(event.get("summary") or ""))


def strip_untreated(summary):
    return UNTREATED_MARK.sub("", summary).strip()


# Added to a booking's description once its public copy exists; the monthly report takes only
# tagged events. Staff may type it by hand for bookings published manually. The web editor
# may store the description as HTML, so the line is matched anywhere, &nbsp; included.
PUBLIC_TAG = "public: yes"
PUBLIC_MARK = re.compile(r"\bpublic:(?:\s|&nbsp;)*yes\b", re.IGNORECASE)


def is_published(event):
    return bool(PUBLIC_MARK.search(event.get("description") or ""))


def add_public_tag(description):
    description = description or ""
    if PUBLIC_MARK.search(description):
        return description
    if description and not description.endswith("\n"):
        description += "\n"
    return description + PUBLIC_TAG + "\n"


def strip_public_tag(description):
    return PUBLIC_MARK.sub("", description or "").strip()


def title(event):
    return event.get("summary") or "Без названия"


def recorded_summ(event):
    # Sum saved in the event's hidden fields, else the "summ: N" line of older bot events
    value = private_props(event).get("summ")
    if value is None:
        match = re.search(r"^summ: (\d+)\s*$", event.get("description") or "", re.MULTILINE)
        value = match.group(1) if match else None
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def money(value):
    return f"{value:,}".replace(",", " ")


def plural(count, one, few, many):
    if count % 10 == 1 and count % 100 != 11:
        return one
    if 2 <= count % 10 <= 4 and not 12 <= count % 100 <= 14:
        return few
    return many


def rents(count):
    return f"{count} {plural(count, 'аренда', 'аренды', 'аренд')}"


def split_month(events):
    # -> (recorded, estimated), each a list of (event, summ, (start, end))
    recorded, estimated = [], []
    for event in events:
        bounds = Dates.event_bounds(event)
        if not bounds or bounds[1] - bounds[0] > datetime.timedelta(hours=MAX_RENT_HOURS):
            continue
        summ = recorded_summ(event)
        if summ == 0:
            # Explicitly marked as "not a rent"
            continue
        if summ is None:
            estimated.append((event, Parser.get_summ(*bounds), bounds))
        else:
            recorded.append((event, summ, bounds))
    return recorded, estimated


def format_report(year, month, recorded, estimated):
    total_recorded = sum(summ for _, summ, _ in recorded)
    total_estimated = sum(summ for _, summ, _ in estimated)
    count = len(recorded) + len(estimated)
    lines = [
        f"Доход за {Dates.MONTHS[month - 1]} {year}: "
        f"{money(total_recorded + total_estimated)} ₽ ({rents(count)})"
    ]
    if not count:
        return lines[0]
    lines += ["", f"С записанной суммой: {money(total_recorded)} ₽ ({len(recorded)})"]
    if estimated:
        lines.append(f"Оценка по текущим тарифам: {money(total_estimated)} ₽ ({len(estimated)})")
    untreated = [summ for event, summ, _ in recorded + estimated if is_untreated(event)]
    if untreated:
        lines.append(f"В т.ч. не обработано: {rents(len(untreated))} на {money(sum(untreated))} ₽")
    if estimated:
        lines += ["", "Без записанной суммы (оценка):"]
        for event, summ, bounds in estimated:
            lines.append(f"• {Dates.format_span(*bounds)} {title(event)} — ~{money(summ)} ₽")
        lines += ["", "Нажмите на событие ниже, чтобы записать точную сумму."]
    return "\n".join(lines)
