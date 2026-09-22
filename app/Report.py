import datetime

import Dates
import Income
from Parser import Parser

SHARE_PERCENT = 20
# The report is made on the last day of the month from this hour (Moscow time)
REPORT_HOUR = 21
# If the bot was down then, it is still made on the first days of the next month
CATCH_UP_DAYS = 3
HEADER = ["Имя клиента", "Дата", "Сумма", "Комментарий", "Процент"]
ESTIMATE_NOTE = "сумма по тарифам"
MANUAL_NOTE = "Не автоматизированная аренда"
# Sheets stores dates as days since this one
EPOCH = datetime.date(1899, 12, 30)

BOLD = {"textFormat": {"bold": True}}
MONEY = {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}}
DATE = {"numberFormat": {"type": "DATE", "pattern": "dd.mm.yyyy"}}


def sheet_title(year, month):
    return f"{Dates.MONTHS[month - 1].capitalize()} {year}"


def due_month(now):
    # (year, month) whose report should exist by `now`, or None
    if (now + datetime.timedelta(days=1)).day == 1 and now.hour >= REPORT_HOUR:
        return now.year, now.month
    if now.day <= CATCH_UP_DAYS:
        previous = now.date().replace(day=1) - datetime.timedelta(days=1)
        return previous.year, previous.month
    return None


def is_manual_rent(event, bounds):
    # Created by hand, so there is no telling whether it was confirmed: listed for a check.
    # Marked untreated means not confirmed; longer events are not rentals (as in Income).
    return (
        not Income.is_bot_event(event)
        and not Income.is_untreated(event)
        and bounds[1] - bounds[0] <= datetime.timedelta(hours=Income.MAX_RENT_HOURS)
    )


def report_rows(events):
    # -> [(name, date, summ, comment)]: bookings with a public copy and events made by hand,
    # by start time
    rows = []
    for event in events:
        bounds = Dates.event_bounds(event)
        if not bounds:
            continue
        if Income.is_published(event):
            comment = ""
        elif is_manual_rent(event, bounds):
            comment = MANUAL_NOTE
        else:
            continue
        summ = Income.recorded_summ(event)
        if summ is None:
            summ, comment = Parser.get_summ(*bounds), comment or ESTIMATE_NOTE
        if summ == 0:
            # Marked "not a rent" in /monthly_income
            continue
        rows.append((bounds[0], Income.strip_untreated(Income.title(event)), summ, comment))
    rows.sort(key=lambda row: row[0])
    return [(name, start.date(), summ, comment) for start, name, summ, comment in rows]


def totals(rows):
    # -> (count, total, share)
    total = sum(summ for _, _, summ, _ in rows)
    return len(rows), total, round(total * SHARE_PERCENT / 100)


def cell(value, style=None):
    # Strings always stay text: a client name starting with "=" must not become a formula
    if isinstance(value, str):
        entered = {"stringValue": value}
    elif isinstance(value, datetime.date):
        entered = {"numberValue": (value - EPOCH).days}
    else:
        entered = {"numberValue": value}
    return {"userEnteredValue": entered, **({"userEnteredFormat": style} if style else {})}


def formula(text, style):
    return {"userEnteredValue": {"formulaValue": text}, "userEnteredFormat": style}


def sheet_requests(sheet_id, title, rows):
    # One batchUpdate is atomic, so a half-filled sheet can't be left behind.
    # Formulas avoid decimals and argument separators, which differ between sheet locales.
    first, last = 2, len(rows) + 1
    data = [{"values": [cell(name, BOLD) for name in HEADER]}]
    for number, (name, date, summ, comment) in enumerate(rows, first):
        data.append(
            {
                "values": [
                    cell(name),
                    cell(date, DATE),
                    cell(summ, MONEY),
                    cell(comment) if comment else {},
                    formula(f"=C{number}*{SHARE_PERCENT}/100", MONEY),
                ]
            }
        )
    bold_money = {**MONEY, **BOLD}
    if rows:
        total, share = (
            formula(f"=SUM({column}{first}:{column}{last})", bold_money) for column in "CE"
        )
    else:
        # SUM(C2:C1) would include the total's own cell
        total = share = cell(0, bold_money)
    data.append({"values": [cell("Итого", BOLD), {}, total, {}, share]})
    return [
        # Without an index the sheet goes last: the bookings sheet must stay first
        {"addSheet": {"properties": {"sheetId": sheet_id, "title": title}}},
        {
            "updateCells": {
                "start": {"sheetId": sheet_id, "rowIndex": 0, "columnIndex": 0},
                "rows": data,
                "fields": "userEnteredValue,userEnteredFormat",
            }
        },
        {
            "autoResizeDimensions": {
                "dimensions": {
                    "sheetId": sheet_id,
                    "dimension": "COLUMNS",
                    "startIndex": 0,
                    "endIndex": len(HEADER),
                }
            }
        },
    ]
