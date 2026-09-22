import unittest

from support import use_tariffs

from Parser import Parser


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


if __name__ == "__main__":
    unittest.main()
