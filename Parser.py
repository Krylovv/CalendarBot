import json
import datetime


class Parser:
    def __init__(self, text):
        self.text = text

    def parse(self):
        result_dict = {}
        required = ['date', 'time', 'hours', 'people', 'Input', 'name']
        # Парсинг словаря из текстового сообщения
        for line in self.text.split('\n'):
            for item in required:
                if item + ':' in line:
                    output = line.split(':')
                    result_dict[output[0]] = output[1][1:]
        # Форматирование даты под %Y-%m-%d
        result_dict['date'] = result_dict['date'].split('-')[2] + '-' + \
            result_dict['date'].split('-')[1] + '-' + result_dict['date'].split('-')[0]
        # Функция подсчета суммы
        summ = self.get_summ(result_dict)
        result_dict['summ'] = str(summ)
        # Блок форматирования словаря под datetime формат и проверки времени работы
        rent_start = datetime.datetime.strptime(result_dict['date'] + " " + result_dict['time'], '%Y-%m-%d %H')
        rent_end = rent_start + datetime.timedelta(hours=int(result_dict['hours']))
        result_dict['end_date'] = str(rent_end.date())
        result_dict['end_time'] = str(rent_end.time())
        result_dict['comment'] = self.check_working_hours(rent_start, rent_end)
        result_dict['time'] = result_dict['time'] + ':00:00'
        return result_dict

    @staticmethod
    def check_working_hours(rent_start, rent_end):
        start_work_time = datetime.time(10, 0, 0)
        end_work_time = datetime.time(23, 0, 0)
        if start_work_time <= rent_start.time() <= end_work_time and \
                start_work_time <= rent_end.time() <= end_work_time:
            return ''
        else:
            return 'Аренда выходит за рамки рабочего дня'

    @staticmethod
    def get_summ(result_dict):
        with open('tarification.json', 'r') as tarifs:
            tariffication_dict = json.load(tarifs)
        in_date = result_dict['date']
        start_time = int(result_dict['time'])
        hours = int(result_dict['hours'])
        day = datetime.datetime.strptime(in_date, '%Y-%m-%d').date().weekday()
        if day <= 3:
            day = "weekday"
        elif day == 4:
            day = "friday"
        else:
            day = "weekend"
        pricing = tariffication_dict[day]
        hours_counter = 0
        result_price = 0
        while hours_counter < hours:
            if start_time + hours_counter < pricing['splitter']:
                result_price += pricing['price'][0]
                hours_counter += 1
            else:
                result_price += pricing['price'][1]
                hours_counter += 1
        return result_price
