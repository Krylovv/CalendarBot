import traceback
from time import sleep

import Dates
import Report
from Calendar import Calendar, EventExists
from GoogleApi import GoogleApi, read_secret
from googleapiclient.discovery import build
from Parser import Parser


class Spreadsheets(GoogleApi):
    # Open-ended range: a fixed "A1:P999" would silently ignore rows past 999
    RANGE_NAME = "A1:P"
    PROCESSED_COLUMN = "P"
    # ~1.5 minutes of failed passes before alerting, so a single network blip stays quiet
    ALERT_AFTER_FAILURES = 3

    def __init__(self, notifier=None):
        super().__init__()
        self.SPREADSHEET_ID = read_secret("spreadsheet_id")
        # Receives new_booking / duplicate_booking / row_error / sync_failed / sync_recovered
        # and monthly_report / report_exists / report_failed
        self.notifier = notifier
        # Month of the last automatic report handled, and of the last failure alert
        self.report_done = None
        self.report_alerted = None

    # Функция обращения к гугл таблице и получения списка событий
    def get_applications(self) -> list:
        service = build("sheets", "v4", credentials=self.creds)
        sheet = service.spreadsheets()
        result = (
            sheet.values()
            .get(spreadsheetId=self.SPREADSHEET_ID, range=self.RANGE_NAME)
            .execute(num_retries=3)
        )
        return result.get("values", [])

    # Функция обновляет значения values в указанных ячейках range_name
    def update_values(self, range_name: str, value_input_option: str, values: list) -> list:
        service = build("sheets", "v4", credentials=self.creds)
        body = {"values": [values]}
        result = (
            service.spreadsheets()
            .values()
            .update(
                spreadsheetId=self.SPREADSHEET_ID,
                range=range_name,
                valueInputOption=value_input_option,
                body=body,
            )
            .execute(num_retries=3)
        )
        return result

    def sheet_ids(self):
        # {title: sheetId} of every sheet
        service = build("sheets", "v4", credentials=self.creds)
        result = (
            service.spreadsheets()
            .get(spreadsheetId=self.SPREADSHEET_ID, fields="sheets.properties(sheetId,title)")
            .execute(num_retries=3)
        )
        return {
            sheet["properties"]["title"]: sheet["properties"]["sheetId"]
            for sheet in result.get("sheets", [])
        }

    def batch_update(self, requests):
        service = build("sheets", "v4", credentials=self.creds)
        # No retries: a retried request that actually succeeded fails on the sheet it added
        return (
            service.spreadsheets()
            .batchUpdate(spreadsheetId=self.SPREADSHEET_ID, body={"requests": requests})
            .execute()
        )

    def build_report(self, year, month, replace=False):
        # -> (title, totals); totals is None when the sheet exists and replace is False
        title = Report.sheet_title(year, month)
        sheets = self.sheet_ids()
        if title in sheets and not replace:
            return title, None
        rows = Report.report_rows(Calendar().get_events_for_month(year, month))
        requests = [{"deleteSheet": {"sheetId": sheets[title]}}] if title in sheets else []
        sheet_id = max(sheets.values(), default=0) + 1
        self.batch_update(requests + Report.sheet_requests(sheet_id, title, rows))
        return title, Report.totals(rows)

    def report_tick(self, now=None):
        # Called every pass; makes the monthly report sheet once (see Report.due_month)
        now = now or Dates.now()
        due = Report.due_month(now)
        if due is None or due == self.report_done:
            return
        try:
            title, totals = self.build_report(*due)
        except Exception as error:
            # Retried on the next pass, alerted once per month; not counted as a sync failure
            traceback.print_exc()
            if due != self.report_alerted:
                self.report_alerted = due
                self.notify("report_failed", *due, error)
            return
        self.report_done = due
        if totals is not None:
            self.notify("monthly_report", *due, title, totals)
        elif due == (now.year, now.month):
            # An existing sheet is never overwritten; most likely made earlier by /monthly_report
            self.notify("report_exists", title)

    @staticmethod
    def row_text(application):
        return (
            "name: "
            + application[0]
            + "\ntg: "
            + application[1]
            + "\ndate: "
            + application[4]
            + "\ntime: "
            + application[5]
            + "\nhours: "
            + application[6]
            + "\npeople: "
            + application[7]
        )

    def mark_processed(self, number):
        # USER_ENTERED keeps the boolean TRUE the sheet has always stored
        self.update_values(self.PROCESSED_COLUMN + str(number), "USER_ENTERED", ["True"])

    def mark_failed(self, number, error):
        # RAW so the message is never interpreted as a formula
        message = f"ОШИБКА: {type(error).__name__}: {error}"
        self.update_values(self.PROCESSED_COLUMN + str(number), "RAW", [message])

    def notify(self, method, *args):
        # Telegram problems must never break the sync
        if self.notifier:
            try:
                getattr(self.notifier, method)(*args)
            except Exception:
                traceback.print_exc()

    # Функция создает события в календаре для каждой необработанной аренды
    def sync_once(self):
        calendar = None
        for number, application in enumerate(self.get_applications(), 1):
            if len(application) >= 16:
                continue
            try:
                result = Parser(self.row_text(application)).parse()
            except (IndexError, KeyError, ValueError) as error:
                # Bad data won't fix itself: flag the row instead of retrying it every pass.
                # Clearing the cell makes the bot try the row again.
                self.mark_failed(number, error)
                self.notify("row_error", number, error)
                continue
            calendar = calendar or Calendar()
            try:
                event, conflicts = calendar.create_event(result, sheet_row=number)
            except EventExists as exists:
                # Created on an earlier pass whose row update failed, or a repeated submission
                self.mark_processed(number)
                self.notify("duplicate_booking", calendar.find_event(exists.event_id), number)
                continue
            # Mark only after the event exists, so a failed insert is retried next pass
            self.mark_processed(number)
            self.notify("new_booking", event, conflicts, number)

    def spreadsheet_to_calendar(self):
        failures = 0
        while True:
            try:
                self.sync_once()
                if failures >= self.ALERT_AFTER_FAILURES:
                    self.notify("sync_recovered")
                failures = 0
            except Exception as error:
                # Keep the sync loop alive on any error (network, auth, API); retry next pass
                traceback.print_exc()
                failures += 1
                if failures == self.ALERT_AFTER_FAILURES:
                    self.notify("sync_failed", error)
            self.report_tick()
            sleep(30)
