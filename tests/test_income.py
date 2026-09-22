import unittest

from support import timed_event, use_tariffs

import Income

MON = "2026-09-21T"


class RecordedSummTest(unittest.TestCase):
    def test_hidden_field_wins(self):
        event = timed_event(
            MON + "19:00:00+03:00", MON + "21:00:00+03:00", private={"summ": "7000"}
        )
        self.assertEqual(Income.recorded_summ(event), 7000)

    def test_legacy_description_line(self):
        description = "type: automated\ntg: @ivan\npeople: 4\nsumm: 9000\ncomment: \n"
        event = timed_event(MON + "19:00:00+03:00", MON + "21:00:00+03:00", description=description)
        self.assertEqual(Income.recorded_summ(event), 9000)
        self.assertTrue(Income.is_bot_event(event))

    def test_manual_event_has_no_sum(self):
        event = timed_event(MON + "19:00:00+03:00", MON + "21:00:00+03:00", description="@ivan")
        self.assertIsNone(Income.recorded_summ(event))
        self.assertFalse(Income.is_bot_event(event))


class UntreatedMarkTest(unittest.TestCase):
    def test_any_spelling_is_listed_and_confirmable(self):
        for summary in ("Иван (не обработана)", "Иван (Не обработана)", "Иван не обработана"):
            self.assertTrue(Income.is_untreated({"summary": summary}), summary)
            self.assertEqual(Income.strip_untreated(summary), "Иван")

    def test_confirmed_titles(self):
        self.assertFalse(Income.is_untreated({"summary": "Иван"}))
        self.assertFalse(Income.is_untreated({}))


class MonthTest(unittest.TestCase):
    def setUp(self):
        use_tariffs(self)

    def test_split_and_estimate(self):
        events = [
            timed_event(MON + "19:00:00+03:00", MON + "21:00:00+03:00", private={"summ": "9000"}),
            # Manual rental: estimated from tariffs, 2 h after the switch = 9000
            timed_event(
                MON + "19:00:00+03:00", MON + "21:00:00+03:00", summary="Пётр", event_id="e2"
            ),
            # Marked "not a rent"
            timed_event(MON + "10:00:00+03:00", MON + "11:00:00+03:00", private={"summ": "0"}),
            # Too long to be a rental
            timed_event(MON + "00:00:00+03:00", "2026-09-23T00:00:00+03:00"),
            {
                "id": "e5",
                "summary": "Праздник",
                "start": {"date": "2026-09-21"},
                "end": {"date": "2026-09-22"},
            },
        ]
        recorded, estimated = Income.split_month(events)
        self.assertEqual([summ for _, summ, _ in recorded], [9000])
        self.assertEqual([(event["id"], summ) for event, summ, _ in estimated], [("e2", 9000)])

    def test_report_text(self):
        untreated = timed_event(
            MON + "19:00:00+03:00",
            MON + "21:00:00+03:00",
            summary="Иван (не обработана)",
            private={"summ": "9000"},
        )
        manual = timed_event(MON + "17:30:00+03:00", MON + "19:30:00+03:00", summary="Пётр")
        recorded, estimated = Income.split_month([untreated, manual])
        report = Income.format_report(2026, 9, recorded, estimated)
        self.assertTrue(report.startswith("Доход за сентябрь 2026: 17 750 ₽ (2 аренды)"))
        self.assertIn("С записанной суммой: 9 000 ₽ (1)", report)
        self.assertIn("Оценка по текущим тарифам: 8 750 ₽ (1)", report)
        self.assertIn("В т.ч. не обработано: 1 аренда на 9 000 ₽", report)
        self.assertIn("• 21.09 пн 17:30–19:30 Пётр — ~8 750 ₽", report)

    def test_empty_month(self):
        self.assertEqual(Income.format_report(2026, 6, [], []), "Доход за июнь 2026: 0 ₽ (0 аренд)")

    def test_plural(self):
        self.assertEqual(
            [Income.rents(n) for n in (1, 2, 5, 11, 21, 22)],
            ["1 аренда", "2 аренды", "5 аренд", "11 аренд", "21 аренда", "22 аренды"],
        )


if __name__ == "__main__":
    unittest.main()
