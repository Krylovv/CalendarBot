import datetime
import unittest

from support import use_tariffs

from Parser import Parser, parse_manual_rent


def booking(time, hours=2, date="21-09-2026", tg="@ivan"):
    # 21-09-2026 is a Monday
    return Parser(
        f"name: Иван\ntg: {tg}\ndate: {date}\ntime: {time}\nhours: {hours}\npeople: 4"
    ).parse()


class ParserTest(unittest.TestCase):
    def setUp(self):
        use_tariffs(self)

    def test_keeps_minutes(self):
        result = booking("19:30")
        self.assertEqual(result["time"], "19:30:00")
        self.assertEqual(result["end_time"], "21:30:00")

    def test_hour_only_and_zero_padding(self):
        self.assertEqual(booking("17")["time"], "17:00:00")
        self.assertEqual(booking("9")["time"], "09:00:00")

    def test_keeps_telegram_link(self):
        self.assertEqual(booking("19:00", tg="https://t.me/ivan")["tg"], "https://t.me/ivan")

    def test_price_by_the_minute_across_switch(self):
        # 30 min at 4000 + 90 min at 4500
        self.assertEqual(booking("17:30")["summ"], "8750")

    def test_price_on_the_hour_unchanged(self):
        self.assertEqual(booking("17:00")["summ"], "8500")
        self.assertEqual(booking("19:00")["summ"], "9000")

    def test_day_types(self):
        self.assertEqual(booking("19:00", date="25-09-2026")["summ"], "10000")  # Friday
        self.assertEqual(booking("15:00", date="26-09-2026")["summ"], "9500")  # Saturday

    def test_crosses_midnight(self):
        result = booking("22:00", hours=4)
        self.assertEqual((result["end_date"], result["end_time"]), ("2026-09-22", "02:00:00"))
        self.assertEqual(result["comment"], "Аренда выходит за рамки рабочего дня")

    def test_description_carries_sum(self):
        self.assertIn("summ: 8750\n", booking("17:30")["description"])

    def test_booking_matches_parse(self):
        # Same fields as a sheet row, but a Parser.booking call: the ID fields must not change
        parsed = booking("17:30")
        built = Parser.booking(
            {"name": "Иван", "tg": "@ivan", "people": "4", "date": "2026-09-21", "hours": "2"},
            datetime.datetime(2026, 9, 21, 17, 30),
            datetime.datetime(2026, 9, 21, 19, 30),
        )
        self.assertEqual(built, parsed)

    def test_booking_fills_date_and_fractional_hours(self):
        result = Parser.booking(
            {"name": "Иван", "tg": "", "people": ""},
            datetime.datetime(2026, 9, 21, 17, 30),
            datetime.datetime(2026, 9, 21, 20, 0),
        )
        self.assertEqual((result["date"], result["hours"]), ("2026-09-21", "2.5"))
        self.assertEqual(result["summ"], "11000")
        self.assertIn("tg: \npeople: \n", result["description"])

    def test_summ_parts(self):
        monday = datetime.datetime(2026, 9, 21)
        self.assertEqual(
            Parser.summ_parts(
                monday.replace(hour=17, minute=30), monday.replace(hour=19, minute=30)
            ),
            [(0.5, 4000), (1.5, 4500)],
        )
        self.assertEqual(
            Parser.summ_parts(monday.replace(hour=19), monday.replace(hour=21)), [(2.0, 4500)]
        )
        self.assertEqual(
            Parser.summ_parts(monday.replace(hour=12), monday.replace(hour=14)), [(2.0, 4000)]
        )


class ManualRentTest(unittest.TestCase):
    TODAY = datetime.date(2026, 9, 28)

    def test_full(self):
        self.assertEqual(
            parse_manual_rent("25.10 19:30 3 Иван Петров @ivan 5", self.TODAY),
            (datetime.datetime(2026, 10, 25, 19, 30), 3.0, "Иван Петров", "@ivan", "5"),
        )

    def test_optional_and_reordered_fields(self):
        self.assertEqual(
            parse_manual_rent("25.10 19 2,5 Анна", self.TODAY),
            (datetime.datetime(2026, 10, 25, 19), 2.5, "Анна", "", ""),
        )
        self.assertEqual(
            parse_manual_rent("25.10.2026 19:00 2 t.me/anna Анна 4", self.TODAY)[2:],
            ("Анна", "t.me/anna", "4"),
        )

    def test_errors(self):
        for text in ("25.10 19:30 Иван", "25.10 19:30 3", "25.10 19:30 3 7", "завтра", ""):
            with self.assertRaises(ValueError, msg=text):
                parse_manual_rent(text, self.TODAY)


if __name__ == "__main__":
    unittest.main()
