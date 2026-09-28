import datetime

import Dates
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
        rent_start = self.parse_start(result_dict["date"], result_dict["time"])
        rent_end = rent_start + datetime.timedelta(hours=int(result_dict["hours"]))
        return self.booking(result_dict, rent_start, rent_end)

    @staticmethod
    def booking(fields, rent_start, rent_end):
        # fields: name, tg, people and optionally date and hours as typed (they are part of the
        # event ID, so a row keeps its own spelling); the rest is computed
        result_dict = dict(fields)
        result_dict.setdefault("date", str(rent_start.date()))
        hours = (rent_end - rent_start) / datetime.timedelta(hours=1)
        result_dict.setdefault("hours", f"{hours:g}")
        result_dict["summ"] = str(Parser.get_summ(rent_start, rent_end))
        result_dict["end_date"] = str(rent_end.date())
        result_dict["end_time"] = str(rent_end.time())
        result_dict["comment"] = Parser.check_working_hours(rent_start, rent_end)
        result_dict["time"] = rent_start.strftime("%H:%M:%S")
        result_dict["description"] = Parser.description(result_dict)
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
    def summ_parts(rent_start, rent_end):
        # -> [(hours, price per hour), ...] before and after the tariff switch hour, without
        # empty parts. Charged by the minute on each side of the switch
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
        day_start = datetime.datetime.combine(rent_start.date(), datetime.time())
        switch = day_start + datetime.timedelta(hours=pricing["splitter"])
        before = max(min(rent_end, switch) - rent_start, datetime.timedelta())
        after = (rent_end - rent_start) - before
        hour = datetime.timedelta(hours=1)
        parts = [(before / hour, price_before), (after / hour, price_after)]
        return [(hours, price) for hours, price in parts if hours > 0]

    @staticmethod
    def get_summ(rent_start, rent_end):
        return round(sum(hours * price for hours, price in Parser.summ_parts(rent_start, rent_end)))

    @staticmethod
    def description(result_dict):
        fields = ("tg", "people", "summ", "comment")
        return "type: automated\n" + "".join(
            f"{field}: {result_dict.get(field, '')}\n" for field in fields
        )


# "25.10 19:30 3 Иван Петров @ivan 5": date, time and hours first, then the name; a word with
# "@" or "t.me/" is the Telegram contact, a trailing number is the number of people
def parse_manual_rent(text, today):
    # -> (start, hours, name, tg, people); ValueError if the date, time, hours or name is missing
    words = text.split()
    start, hours = Dates.parse_move(" ".join(words[:3]), today)
    if hours is None:
        raise ValueError("hours are required")
    rest = words[3:]
    contacts = [word for word in rest if word.startswith("@") or "t.me/" in word]
    rest = [word for word in rest if word not in contacts]
    people = rest.pop() if rest and rest[-1].isdigit() else ""
    if not rest:
        raise ValueError("name is required")
    return start, hours, " ".join(rest), " ".join(contacts), people
