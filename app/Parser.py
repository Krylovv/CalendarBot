import json
import datetime

import Tariffs


class Parser:
    def __init__(self, text):
        self.text = text

    def parse(self):
        result_dict = {}
        required = ["date", "time", "hours", "people", "tg", "name"]
        # Парсинг словаря из текстового сообщения
        for line in self.text.split("\n"):
            for item in required:
                if item + ":" in line:
                    # Split on the first colon only, so "time: 19:30" keeps its minutes
                    key, value = line.split(":", 1)
                    result_dict[key] = value.strip()
        # Форматирование даты под %Y-%m-%d
        result_dict["date"] = (
            result_dict["date"].split("-")[2]
            + "-"
            + result_dict["date"].split("-")[1]
            + "-"
            + result_dict["date"].split("-")[0]
        )
        # Блок форматирования словаря под datetime формат и проверки времени работы
        rent_start = self.parse_start(result_dict["date"], result_dict["time"])
        rent_end = rent_start + datetime.timedelta(hours=int(result_dict["hours"]))
        # Функция подсчета суммы
        result_dict["summ"] = str(self.get_summ(rent_start, rent_end))
        result_dict["end_date"] = str(rent_end.date())
        result_dict["end_time"] = str(rent_end.time())
        result_dict["comment"] = self.check_working_hours(rent_start, rent_end)
        result_dict["time"] = rent_start.strftime("%H:%M:%S")
        result_dict["description"] = self.description(result_dict)
        return result_dict

    @staticmethod
    def check_working_hours(rent_start, rent_end):
        start_work_time = datetime.time(10, 0, 0)
        end_work_time = datetime.time(23, 0, 0)
        if (
            start_work_time <= rent_start.time() <= end_work_time
            and start_work_time <= rent_end.time() <= end_work_time
        ):
            return ""
        else:
            return "Аренда выходит за рамки рабочего дня"

    @staticmethod
    def parse_start(date, time):
        # Accepts "19", "19:30" or "19:30:00"
        parts = time.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return datetime.datetime.strptime(date, "%Y-%m-%d").replace(hour=hour, minute=minute)

    @staticmethod
    def get_summ(rent_start, rent_end):
        tariffication_dict = Tariffs.load()
        day = rent_start.weekday()
        if day <= 3:
            day = "weekday"
        elif day == 4:
            day = "friday"
        else:
            day = "weekend"
        pricing = tariffication_dict[day]
        price_before, price_after = pricing["price"]
        # Charge by the minute on each side of the tariff switch hour
        day_start = datetime.datetime.combine(rent_start.date(), datetime.time())
        switch = day_start + datetime.timedelta(hours=pricing["splitter"])
        before = max(min(rent_end, switch) - rent_start, datetime.timedelta())
        after = (rent_end - rent_start) - before
        hour = datetime.timedelta(hours=1)
        return round(before / hour * price_before + after / hour * price_after)

    @staticmethod
    def description(result_dict):
        try:
            tg = result_dict["tg"]
            people = result_dict["people"]
            summ = result_dict["summ"]
            comment = result_dict["comment"]
            d = f'"type": "automated", "tg": "{tg}", "people": {people}, "summ": {summ}, "comment": "{comment}"'
            d = "{" + d + "}"
            d = json.loads(d)
            s = ""
            for key in d:
                s += key + ": " + str(d[key]) + "\n"
            return s
        except Exception:
            return

    @staticmethod
    def get_monthly_rent_income(descriptions):
        summ = 0
        try:
            for description in descriptions:
                for line in description.split("\n"):
                    if "summ" in line:
                        summ += int(line.split(":")[1][1:])
            return summ
        except Exception:
            return
