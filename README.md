# CalendarBot

A Telegram bot (Russian UI) for a rental venue. It turns booking requests from a Google Sheet into Google Calendar events, notifies staff about every new booking, publishes confirmed bookings to a public calendar, and makes a monthly report sheet.

## Features

**Automatic sync.** Every 30 seconds the bot reads the bookings sheet. Each new row becomes a calendar event titled `<name> (не обработана)`, and the row is marked `TRUE` in column P. The row is marked only after the event exists, so nothing is lost if Google is unreachable.

**Booking notifications.** Every authorized user gets a card for each new booking: time, duration, price, overlaps with other events, and a warning if it's outside working hours (10:00–23:00). Buttons: **✅ Подтвердить** copies the booking to the public calendar (client name and time only, empty description), then removes "(не обработана)" from the title and appends the line `public: yes` to the description. **❌ Отменить** deletes the event from both calendars (after a confirmation). Confirming twice never creates a second public copy.

**Monthly report.** On the last day of the month at 21:00 (Moscow time) the bot adds a sheet named like `Сентябрь 2026` to the bookings spreadsheet: every event of the month tagged `public: yes`, plus events created by hand (it's unknown whether they were confirmed, so they get a tariff estimate unless a sum was recorded in `/monthly_income`, and the comment "Не автоматизированная аренда"). Columns: Имя клиента, Дата, Сумма, Комментарий, Процент (20% as a formula), and a total row. Bot bookings without the tag, events marked "(не обработана)", all-day events, events over 12 hours and events with sum 0 are left out. If the bot was down, the sheet is made on the next start, up to the 3rd. An existing sheet is never overwritten.

**Safety nets**
- A row that can't be parsed gets `ОШИБКА: …` in column P plus a Telegram alert. Fix the row and clear the cell to retry.
- Each booking has a deterministic event ID, so retries and repeated submissions never create duplicates.
- If syncing fails for about 1.5 minutes (3 passes), the bot sends one alert, and another when it recovers.

**Commands**

| Command | What it does |
|---|---|
| `/next_week_rents` | Events for next week, Monday–Sunday |
| `/untreated_rents` | Unconfirmed bookings for the next 180 days, each as a card with ✅/❌ buttons, so a lost notification never loses a booking (up to 10 cards per request) |
| `/monthly_income` | Pick a month, get income. Events with a recorded sum are counted exactly; events without one (e.g. created by hand) are priced from the tariffs and listed with ✏️ buttons to record the real sum, or `0` for "not a rental". |
| `/monthly_report` | Make the report sheet for the current month (from the 1st) right now. If the sheet exists, offers to rebuild it |
| `/tariffs` | View and edit prices from Telegram |
| `/about` | Help text describing all of the above |

Pasting a booking message from `outcinema.ru/rent` into the chat creates the event right away.

**Pricing.** There are three day types: weekday (Mon–Thu), Friday and weekend. Each has an hourly price before and after a switch hour. Time is charged by the minute on each side of the switch: 17:30–19:30 with an 18:00 switch is 30 minutes at the first price plus 1.5 hours at the second. Prices live in `data/tarification.json` and are edited with `/tariffs`. `tarification.json` in the repo only holds the initial values.

## Bookings sheet format

The bot reads the first tab of the sheet, starting at row 1. Monthly report sheets are added at the end: keep the bookings tab first.

| Column | Content | Example |
|---|---|---|
| A | Client name | `Иван` |
| B | Telegram handle or link | `@ivan` |
| E | Date, `DD-MM-YYYY` | `23-09-2026` |
| F | Start time, `HH:MM` | `19:30` |
| G | Duration, whole hours | `3` |
| H | Number of people | `5` |
| P | Filled in by the bot: `TRUE` = done, `ОШИБКА: …` = couldn't parse | |

A row is treated as processed as soon as column P is non-empty. The other columns are ignored.

## Setup

### 1. Google service account

The bot signs in to Google as a service account: no browser login, and nothing expires.

1. In [Google Cloud Console](https://console.cloud.google.com), pick or create a project. Enable the [Google Sheets API](https://console.cloud.google.com/apis/library/sheets.googleapis.com) and the [Google Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com).
2. Go to **IAM & Admin → Service Accounts → Create service account**. Skip the roles step. Copy the account's email (`…@….iam.gserviceaccount.com`).
3. Open the account, go to **Keys → Add key → Create new key → JSON**, and save the file as `secrets/service_account.json`.
4. **Sheet:** Share → add the service account email as **Editor**. The bot writes column P.
5. **Calendar:** on calendar.google.com, go to **Settings and sharing → Share with specific people** and add the email with **Make changes to events**. Copy the **Calendar ID** from **Integrate calendar** into `secrets/calendar_id`.
6. **Public calendar:** create a separate calendar, turn on **Make available to public**, share it with the service account email with **Make changes to events**, and copy its Calendar ID into `secrets/public_calendar_id`.

### 2. Secrets

All files in `secrets/` are gitignored. Never commit them.

| File | Content |
|---|---|
| `secrets/bot_token` | Telegram bot token from @BotFather |
| `secrets/telegram_ids` | Authorized Telegram user IDs, one per line (matched exactly) |
| `secrets/spreadsheet_id` | The Google Sheet ID (the long part of its URL) |
| `secrets/calendar_id` | Target calendar ID |
| `secrets/public_calendar_id` | Public calendar ID (confirmed bookings, name and time only) |
| `secrets/service_account.json` | Service account key from step 1 |

### 3. Run locally

Always run from the repo root; paths like `./secrets/` are relative:

```
python3 -m venv venv
venv/bin/pip install -r req.txt
venv/bin/python app/main.py
```

Only one copy of the bot can run per Telegram token. Stop the server copy first, or both will fail with `409 Conflict`.

## Deploy with Docker

Build the image on the server itself (the Dockerfile uses `python:3.12-alpine`). The image contains no secrets; they are mounted at runtime, along with a persistent folder for the tariffs.

```
sudo mkdir -p /srv/calendarbot/secrets /srv/calendarbot/data
# copy the 6 secret files into /srv/calendarbot/secrets/

git clone https://github.com/Krylovv/CalendarBot.git ~/CalendarBot
cd ~/CalendarBot && docker build -t calendarbot .
docker run -d --name calendarbot --restart unless-stopped \
  -v /srv/calendarbot/secrets:/opt/secrets:ro \
  -v /srv/calendarbot/data:/opt/data \
  calendarbot
docker logs -f calendarbot
```

Mount the `data` folder, not the single file: tariffs are saved by atomic replace, which fails on a single bind-mounted file.

**Updating:**

```
cd ~/CalendarBot && git pull && docker build -t calendarbot . && docker rm -f calendarbot
# then the same docker run command as above
```

After an update that changes commands, send `/start` once to refresh the Telegram command menu.

## Tests

```
venv/bin/python -m unittest discover -s tests
```

The tests use only the standard library and need no secrets or network. Lint with `ruff check app tests` (settings in `pyproject.toml`).

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `403 … The caller does not have permission` | The sheet isn't shared with the service account as Editor |
| `404 Not Found` on calendar calls | The calendar isn't shared with the service account, or `calendar_id` is wrong |
| ✅/❌ answer "Тут какая-то ошибка" | `secrets/public_calendar_id` is missing, or the public calendar isn't shared with the service account |
| `403 … API has not been used in project` | Enable the Sheets / Calendar API in the service account's project |
| `invalid_grant` / `Invalid JWT Signature` | The key was deleted or disabled: create a new JSON key |
| `409 Conflict` in the logs | Another copy of the bot is running with the same token |
| A row shows `ОШИБКА: …` in column P | Fix the row's date, time or hours, then clear the cell |

## Project layout

```
app/main.py         entry point: Telegram polling + sheet sync threads
app/Bot.py          commands, buttons, notifications
app/Spreadsheet.py  sheet reading and the sync loop
app/Calendar.py     Google Calendar access
app/Parser.py       booking parsing and pricing
app/Income.py       monthly income report
app/Report.py       monthly report sheet
app/Tariffs.py      tariffs storage
app/Dates.py        Moscow-time helpers
tests/              unit tests
```
