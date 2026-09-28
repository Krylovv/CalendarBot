import datetime
import os

import Dates

# Next week's rents are sent on Thursdays from this hour (Moscow time)
DIGEST_WEEKDAY = 3
DIGEST_HOUR = 10
# Monday of the last week sent, kept in ./data so a restart doesn't send it again
SENT_PATH = "./data/weekly_rents_sent"


def due_week(now):
    # Monday of the week whose digest should be sent by `now`, or None. If the bot was down
    # on Thursday, it is still sent until Sunday
    thursday = Dates.start_of(now.date() - datetime.timedelta(days=now.weekday() - DIGEST_WEEKDAY))
    if now < thursday.replace(hour=DIGEST_HOUR):
        return None
    return Dates.next_week_range(now.date())[0]


def last_sent():
    try:
        with open(SENT_PATH) as f:
            return Dates.start_of(datetime.date.fromisoformat(f.read().strip()))
    except (OSError, ValueError):
        return None


def mark_sent(monday):
    os.makedirs(os.path.dirname(SENT_PATH), exist_ok=True)
    with open(SENT_PATH, "w") as f:
        f.write(monday.date().isoformat())
