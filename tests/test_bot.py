import datetime
import itertools
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httplib2
from googleapiclient.errors import HttpError
from support import timed_event, use_tariffs

from Bot import (
    ABOUT,
    COMMANDS,
    Bot,
    booking_card,
    describe_error,
    format_event,
    invoice_message,
    move_preview,
    new_rent_preview,
    next_week_text,
    report_callback,
    report_text,
    split_message,
    tg_username,
)
from Parser import Parser


class AboutTest(unittest.TestCase):
    def test_about_describes_every_menu_command(self):
        for command, _ in COMMANDS:
            self.assertIn(f"/{command} — ", ABOUT)

    def test_about_fits_one_message(self):
        self.assertLessEqual(len(ABOUT), 4096)


class SplitMessageTest(unittest.TestCase):
    def test_splits_between_lines_under_limit(self):
        text = "\n".join(f"строка {number} " + "x" * 50 for number in range(300))
        chunks = split_message(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 4096 for chunk in chunks))
        self.assertEqual("\n".join(chunks), text)

    def test_splits_a_single_huge_line(self):
        chunks = split_message("x" * 10000)
        self.assertEqual([len(chunk) for chunk in chunks], [4096, 4096, 1808])

    def test_short_text_untouched(self):
        self.assertEqual(split_message("привет"), ["привет"])


class AccessTest(unittest.TestCase):
    def test_ids_are_matched_exactly(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        secrets = Path(folder.name) / "secrets"
        secrets.mkdir()
        (secrets / "bot_token").write_text("123:TEST\n")
        (secrets / "telegram_ids").write_text("5123456789\n111222333\n")
        cwd = os.getcwd()
        os.chdir(folder.name)
        self.addCleanup(os.chdir, cwd)
        bot = Bot()
        allowed = [
            bot.allowed(SimpleNamespace(id=user_id))
            for user_id in (5123456789, 111222333, 512345678, 123456789, 12345)
        ]
        self.assertEqual(allowed, [True, True, False, False, False])


class CallbackDataTest(unittest.TestCase):
    def setUp(self):
        self.bot = Bot.__new__(Bot)
        self.bot.callback_ids = {}

    def test_bot_event_ids_fit_directly(self):
        event_id = "cb" + "0" * 40
        data = self.bot.event_callback("bk:rmy", event_id)
        self.assertEqual(data, "bk:rmy:" + event_id)
        self.assertLessEqual(len(data), 64)

    def test_long_ids_use_tokens(self):
        event_id = "a" * 70
        data = self.bot.event_callback("inc:s", event_id)
        self.assertEqual(data, "inc:s:~0")
        self.assertEqual(self.bot.resolve_event_id(data.split(":", 2)[2]), event_id)


class FormattingTest(unittest.TestCase):
    def setUp(self):
        use_tariffs(self)

    def test_booking_card(self):
        event = timed_event(
            "2026-09-23T19:30:00+03:00",
            "2026-09-23T23:30:00+03:00",
            summary="Иван (не обработана)",
            description="type: automated\ntg: @ivan\npeople: 5\nsumm: 22000\n"
            "comment: Аренда выходит за рамки рабочего дня, Аренда пересекается с другими событиями\n",
            private={"source": "calendarbot", "summ": "22000"},
        )
        other = timed_event(
            "2026-09-23T19:00:00+03:00", "2026-09-23T21:00:00+03:00", summary="Пётр"
        )
        self.assertEqual(
            booking_card(event, [other]).splitlines(),
            [
                "Иван · @ivan · 5 чел.",
                "23.09 ср 19:30–23:30 (4 ч)",
                "Сумма: 22 000 ₽",
                "⚠️ Пересекается: 23.09 ср 19:00–21:00 Пётр",
                "⚠️ Аренда выходит за рамки рабочего дня",
            ],
        )

    def test_format_manual_and_all_day_events(self):
        manual = timed_event(
            "2026-09-24T19:30:00+03:00",
            "2026-09-24T21:30:00+03:00",
            summary="Анна",
            description="@anna\nзвонила",
        )
        self.assertEqual(format_event(manual), "24.09 чт 19:30–21:30\nАнна\n@anna")
        manual["description"] = "public: yes\n"
        self.assertEqual(format_event(manual), "24.09 чт 19:30–21:30\nАнна")
        all_day = {
            "summary": "Праздник",
            "start": {"date": "2026-09-27"},
            "end": {"date": "2026-09-28"},
        }
        self.assertEqual(format_event(all_day), "27.09 вс весь день\nПраздник")

    def test_next_week_text(self):
        untreated = timed_event(
            "2026-10-05T19:00:00+03:00",
            "2026-10-05T21:00:00+03:00",
            summary="Иван (не обработана)",
            private={"summ": "9000"},
        )
        invoiced = timed_event(
            "2026-10-06T12:00:00+03:00",
            "2026-10-06T14:00:00+03:00",
            summary="Пётр",
            private={
                "summ": "8000",
                "invoice_id": "i1",
                "invoice_status": "NotPaid",
                "invoice_expires": "2026-10-03T12:00:00+03:00",
            },
        )
        paid = timed_event(
            "2026-10-07T12:00:00+03:00",
            "2026-10-07T14:00:00+03:00",
            summary="Анна",
            private={"summ": "8000", "invoice_id": "i2", "invoice_status": "Paid"},
        )
        text = next_week_text(datetime.datetime(2026, 10, 5), [untreated, invoiced, paid])
        self.assertTrue(text.startswith("Аренды на следующую неделю (05.10–11.10): 3\n\n"))
        self.assertTrue(
            text.endswith(
                "💳 Не оплачены (2):\n"
                "• 05.10 пн 19:00–21:00 Иван · 9 000 ₽ · счёт не выставлен\n"
                "• 06.10 вт 12:00–14:00 Пётр · 8 000 ₽ · счёт до 03.10 12:00"
            )
        )
        self.assertTrue(
            next_week_text(datetime.datetime(2026, 10, 5), [paid]).endswith("Неоплаченных нет")
        )
        self.assertEqual(
            next_week_text(datetime.datetime(2026, 10, 5), []),
            "Аренды на следующую неделю (05.10–11.10): нет",
        )

    def test_report_text(self):
        self.assertEqual(
            report_text(2026, 9, "Сентябрь 2026", (12, 180000, 36000)),
            "📊 Отчёт за сентябрь 2026 готов — лист «Сентябрь 2026» в таблице заявок\n"
            "12 аренд · 180 000 ₽ · 20% — 36 000 ₽",
        )

    def test_error_description_has_no_urls(self):
        error = HttpError(
            httplib2.Response({"status": 404}),
            b'{"error": {"message": "Not Found"}}',
            uri="https://sheets.googleapis.com/v4/spreadsheets/SECRET_ID/values",
        )
        self.assertEqual(describe_error(error), "HTTP 404: Not Found")


def bot_booking(summ="18000"):
    # Wed 19:30-23:30 by the test tariffs: 4 * 4500 = 18000
    return timed_event(
        "2026-09-23T19:30:00+03:00",
        "2026-09-23T23:30:00+03:00",
        summary="Иван",
        description="type: automated\ntg: @ivan\npeople: 5\nsumm: 18000\ncomment: \npublic: yes\n",
        private={"source": "calendarbot", "summ": summ},
        event_id="cb1",
    )


class MoveTest(unittest.TestCase):
    START, END = datetime.datetime(2026, 10, 3, 21), datetime.datetime(2026, 10, 3, 23, 30)

    def setUp(self):
        use_tariffs(self)
        now = mock.patch("Dates.now", return_value=datetime.datetime(2026, 9, 27, 12))
        now.start()
        self.addCleanup(now.stop)

    def test_preview_with_tariff_sum(self):
        other = timed_event(
            "2026-10-03T22:00:00+03:00", "2026-10-04T00:00:00+03:00", summary="Пётр"
        )
        self.assertEqual(
            move_preview(bot_booking(), self.START, self.END, [other]).splitlines(),
            [
                "📅 Перенести аренду?",
                "Иван · @ivan · 5 чел.",
                "Было: 23.09 ср 19:30–23:30 (4 ч)",
                "Станет: 03.10 сб 21:00–23:30 (2,5 ч)",
                "Сумма по тарифу: 18 000 → 12 500 ₽ (2,5 ч × 5 000)",
                "⚠️ Пересекается: 03.10 сб 22:00–00:00 Пётр",
                "⚠️ Аренда выходит за рамки рабочего дня",
                "Публичная копия тоже будет перенесена",
            ],
        )

    def test_preview_keeps_discount(self):
        lines = move_preview(bot_booking(summ="15000"), self.START, self.END, []).splitlines()
        self.assertIn("Сумма: 15 000 ₽", lines)
        self.assertIn("Сумма изменена вручную и не пересчитается (по тарифу 12 500 ₽)", lines)

    def test_move_button_works_once(self):
        bot = Bot.__new__(Bot)
        bot.callback_ids, bot.moves, bot.move_tokens = {}, {}, itertools.count()
        bot.bot = mock.Mock()
        bot.moves["0"] = ("cb1", self.START, self.END, None)
        call = SimpleNamespace(
            data="mv:ok:0",
            message=SimpleNamespace(chat=SimpleNamespace(id=1), message_id=2, text="превью"),
            from_user=SimpleNamespace(first_name="Аня"),
        )
        with mock.patch("Bot.Calendar") as calendar:
            calendar.return_value.move_event.return_value = (bot_booking(), [])
            self.assertEqual(bot.handle_move_action(call), "Перенесено")
            self.assertEqual(bot.handle_move_action(call), "Кнопка устарела")
        calendar.return_value.move_event.assert_called_once_with("cb1", self.START, self.END)

    def test_unpaid_buttons_open_booking_card(self):
        bot = Bot.__new__(Bot)
        bot.callback_ids, bot.bot = {}, mock.Mock()
        untreated = bot_booking()
        untreated["summary"] = "Иван (не обработана)"
        confirmed = timed_event(
            "2026-10-06T12:00:00+03:00", "2026-10-06T14:00:00+03:00", summary="Пётр", event_id="cb2"
        )
        markup = bot.next_week_markup([untreated, confirmed])
        buttons = [row[0] for row in markup.keyboard]
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].text, "Иван · 23.09 ср 19:30")
        self.assertEqual(buttons[0].callback_data, "bk:card:" + untreated["id"])
        self.assertIsNone(bot.next_week_markup([confirmed]))
        call = SimpleNamespace(
            data=buttons[0].callback_data,
            message=SimpleNamespace(chat=SimpleNamespace(id=1), message_id=2, text="список"),
            from_user=SimpleNamespace(first_name="Аня"),
        )
        with mock.patch("Bot.Calendar") as calendar:
            calendar.return_value.find_event.return_value = untreated
            self.assertIsNone(bot.handle_booking_action(call))
            calendar.return_value.find_event.return_value = None
            self.assertEqual(bot.handle_booking_action(call), "Событие уже удалено")
        # The card is a new message; the list itself is never edited
        bot.bot.send_message.assert_called_once()
        self.assertEqual(bot.bot.send_message.call_args[0][1], booking_card(untreated))
        bot.bot.edit_message_text.assert_not_called()


def with_invoice(event, status="NotPaid", summ="18000", test="1"):
    event["extendedProperties"]["private"].update(
        invoice_id="inv1",
        invoice_number="123285133",
        invoice_url="https://pay/inv1",
        invoice_status=status,
        invoice_summ=summ,
        invoice_expires="2026-10-04T12:00:00+03:00",
        invoice_test=test,
    )
    return event


class InvoiceTest(unittest.TestCase):
    def setUp(self):
        use_tariffs(self)
        self.bot = Bot.__new__(Bot)
        self.bot.callback_ids, self.bot.ids = {}, set()
        self.bot.bot = mock.Mock()
        self.calendar = mock.Mock()
        self.patch("Bot.Robokassa.configured", return_value=True)
        self.create = self.patch("Bot.Robokassa.create_invoice")
        self.deactivate = self.patch("Bot.Robokassa.deactivate")

    def patch(self, target, **kwargs):
        patcher = mock.patch(target, **kwargs)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def call(self, action="iv"):
        return SimpleNamespace(
            data=f"bk:{action}:cb1",
            message=SimpleNamespace(chat=SimpleNamespace(id=1), message_id=2, text="карточка"),
            from_user=SimpleNamespace(first_name="Аня"),
        )

    def buttons(self, event):
        markup = self.bot.booking_markup(event)
        return [key.text for row in markup.keyboard for key in row]

    def sent(self):
        return [call.args[1] for call in self.bot.bot.send_message.call_args_list]

    def test_card_and_forwardable_message(self):
        event = with_invoice(bot_booking())
        self.assertIn(
            "💳 Счёт №123285133 (тест) на 18 000 ₽: не оплачен (до 04.10 12:00)",
            booking_card(event),
        )
        self.assertEqual(
            invoice_message(event),
            "Аренда 23.09 ср 19:30–23:30\n"
            "По стоимости у вас получится 18 000 ₽\nПредоплата: https://pay/inv1",
        )
        self.assertNotIn("@ivan", invoice_message(event))

    def test_button_needs_config_sum_and_unpaid_invoice(self):
        self.assertIn("💳 Счёт", self.buttons(bot_booking()))
        self.assertNotIn("💳 Счёт", self.buttons(bot_booking(summ="0")))
        self.assertNotIn("💳 Счёт", self.buttons(with_invoice(bot_booking(), "Paid")))
        with mock.patch("Bot.Robokassa.configured", return_value=False):
            self.assertNotIn("💳 Счёт", self.buttons(bot_booking()))

    def test_issue_saves_and_sends_link(self):
        self.calendar.find_event.return_value = bot_booking()
        self.create.return_value = {"id": "inv1", "test": True}
        self.calendar.set_invoice.return_value = with_invoice(bot_booking())
        with mock.patch("Bot.Calendar", return_value=self.calendar):
            self.assertEqual(self.bot.handle_booking_action(self.call()), "Счёт выставлен")
        self.create.assert_called_once_with(18000, "Аренда зала 23.09.2026 19:30–23:30")
        self.calendar.set_invoice.assert_called_once_with("cb1", {"id": "inv1", "test": True})
        self.assertIn("https://pay/inv1", self.sent()[0])

    def test_repeated_tap_resends_the_same_link(self):
        event = with_invoice(bot_booking())
        self.calendar.find_event.return_value = event
        self.calendar.refresh_invoice.return_value = (event, None)
        with mock.patch("Bot.Calendar", return_value=self.calendar):
            self.assertEqual(self.bot.handle_booking_action(self.call()), "Счёт уже выставлен")
        self.create.assert_not_called()
        self.assertIn("https://pay/inv1", self.sent()[0])

    def test_expired_invoice_is_replaced(self):
        event = with_invoice(bot_booking())
        self.calendar.find_event.return_value = event
        self.calendar.refresh_invoice.return_value = (
            with_invoice(bot_booking(), "Expired"),
            "Expired",
        )
        self.create.return_value = {"id": "inv2", "test": True}
        self.calendar.set_invoice.return_value = event
        with mock.patch("Bot.Calendar", return_value=self.calendar):
            self.assertEqual(self.bot.handle_booking_action(self.call()), "Счёт выставлен")
        self.calendar.set_invoice.assert_called_once_with("cb1", {"id": "inv2", "test": True})

    def test_unsaved_invoice_is_deactivated(self):
        self.calendar.find_event.return_value = bot_booking()
        self.create.return_value = {"id": "inv1", "test": True}
        self.calendar.set_invoice.side_effect = TimeoutError("down")
        with (
            mock.patch("Bot.Calendar", return_value=self.calendar),
            self.assertRaises(TimeoutError),
        ):
            self.bot.handle_booking_action(self.call())
        self.deactivate.assert_called_once_with("inv1", True)

    def test_delete_cancels_unpaid_invoice_first(self):
        event = with_invoice(bot_booking())
        self.calendar.find_event.return_value = event
        self.calendar.close_invoice.return_value = (event, "Cancelled")
        with mock.patch("Bot.Calendar", return_value=self.calendar):
            self.assertEqual(self.bot.handle_booking_action(self.call("rmy")), "Событие удалено")
        self.assertEqual(
            [name for name, _, _ in self.calendar.method_calls],
            ["find_event", "close_invoice", "delete_event"],
        )

    def test_delete_stops_when_invoice_was_just_paid(self):
        self.calendar.find_event.return_value = with_invoice(bot_booking())
        paid = with_invoice(bot_booking(), "Paid")
        self.calendar.close_invoice.return_value = (paid, "Paid")
        with mock.patch("Bot.Calendar", return_value=self.calendar):
            self.assertEqual(self.bot.handle_booking_action(self.call("rmy")), "Счёт оплачен")
        self.calendar.delete_event.assert_not_called()

    def test_changed_sum_cancels_unpaid_invoice(self):
        event = with_invoice(bot_booking(summ="15000"))
        self.calendar.close_invoice.return_value = (event, "Cancelled")
        _, note = self.bot.invoice_after_summ_change(self.calendar, event)
        self.assertEqual(note, "💳 Сумма изменилась, старый счёт отменён: выставьте новый")
        self.calendar.close_invoice.assert_called_once()

    def test_changed_sum_after_payment_is_flagged(self):
        event = with_invoice(bot_booking(summ="15000"), "Paid")
        _, note = self.bot.invoice_after_summ_change(self.calendar, event)
        self.assertIn("уже оплачен", note)
        self.calendar.close_invoice.assert_not_called()

    def test_same_sum_keeps_invoice(self):
        _, note = self.bot.invoice_after_summ_change(self.calendar, with_invoice(bot_booking()))
        self.assertIsNone(note)
        self.calendar.close_invoice.assert_not_called()


class CardExtrasTest(unittest.TestCase):
    def setUp(self):
        use_tariffs(self)
        self.bot = Bot.__new__(Bot)
        self.bot.callback_ids = {}

    def links(self, tg):
        event = bot_booking()
        event["description"] = event["description"].replace("@ivan", tg)
        markup = self.bot.booking_markup(event)
        return [key.url for row in markup.keyboard for key in row if key.url]

    def test_tg_username(self):
        for value in ("@ivan_p", "ivan_p", "t.me/ivan_p", "https://t.me/ivan_p/", " @ivan_p "):
            self.assertEqual(tg_username(value), "ivan_p", value)
        for value in ("+79991234567", "Иван", "@ab", "@ivan p", "", None, "@1ivan"):
            self.assertIsNone(tg_username(value), value)

    def test_write_button_only_for_valid_username(self):
        self.assertEqual(self.links("@ivan_p"), ["https://t.me/ivan_p"])
        self.assertEqual(self.links("89991234567"), [])

    def test_tariff_breakdown_in_card(self):
        # Mon 17:30-19:30: 30 min at 4000 and 90 min at 4500
        event = timed_event(
            "2026-09-21T17:30:00+03:00",
            "2026-09-21T19:30:00+03:00",
            description="type: automated\ntg: @ivan\npeople: 5\nsumm: 8750\n",
            private={"source": "calendarbot", "summ": "8750"},
        )
        self.assertIn("Сумма: 8 750 ₽ (0,5 ч × 4 000 + 1,5 ч × 4 500)", booking_card(event))
        # A sum set by hand has no breakdown
        event["extendedProperties"]["private"]["summ"] = "8000"
        self.assertIn("Сумма: 8 000 ₽\n", booking_card(event) + "\n")


class NewRentTest(unittest.TestCase):
    def setUp(self):
        use_tariffs(self)
        now = mock.patch("Dates.now", return_value=datetime.datetime(2026, 9, 20, 12))
        now.start()
        self.addCleanup(now.stop)

    def test_preview(self):
        start, end = datetime.datetime(2026, 9, 21, 17, 30), datetime.datetime(2026, 9, 21, 23, 30)
        result = Parser.booking({"name": "Иван Петров", "tg": "", "people": "5"}, start, end)
        other = timed_event(
            "2026-09-21T22:00:00+03:00", "2026-09-22T00:00:00+03:00", summary="Пётр"
        )
        self.assertEqual(
            new_rent_preview(result, start, end, [other]).splitlines(),
            [
                "🆕 Добавить аренду?",
                "Иван Петров · 5 чел.",
                "21.09 пн 17:30–23:30 (6 ч)",
                "Сумма по тарифу: 26 750 ₽ (0,5 ч × 4 000 + 5,5 ч × 4 500)",
                "⚠️ Пересекается: 21.09 пн 22:00–00:00 Пётр",
                "⚠️ Аренда выходит за рамки рабочего дня",
            ],
        )


class ReportCallbackTest(unittest.TestCase):
    def test_actions(self):
        self.assertEqual(report_callback("rep:m:2026-09"), ("m", "2026-09"))
        self.assertEqual(report_callback("rep:y:2025"), ("y", "2025"))
        self.assertEqual(report_callback("rep:r:2026-09"), ("r", "2026-09"))
        # Rebuild buttons sent before the month picker
        self.assertEqual(report_callback("rep:2026-09"), ("r", "2026-09"))

    def test_month_picker_prefix(self):
        bot = Bot.__new__(Bot)
        markup = bot.month_picker(2026, "rep")
        data = [key.callback_data for row in markup.keyboard for key in row]
        self.assertIn("rep:m:2026-09", data)
        self.assertIn("rep:y:2025", data)
        self.assertTrue(all(value.startswith("rep:") for value in data))


if __name__ == "__main__":
    unittest.main()
