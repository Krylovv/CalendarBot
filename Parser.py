import json
import datetime


class Parser:
    def __init__(self, text):
        self.text = text

    def parse(self):
        result_dict = {}
        message = ''
        required = ['date', 'time', 'hours', 'people', 'Input', 'name']
        # Парсинг словаря из текстового сообщения
        print("1")
        for line in self.text.split('\n'):
            for item in required:
                if item + ':' in line:
                    output = line.split(':')
                    result_dict[output[0]] = output[1][1:]
        # Форматирование даты под %Y-%m-%d
        print("2")
        result_dict['date'] = result_dict['date'].split('-')[2] + '-' + result_dict['date'].split('-')[1] + '-' + result_dict['date'].split('-')[0]

        # Функция подсчета суммы
        summ = self.get_summ(result_dict)
        print("3")
        result_dict['summ'] = str(summ)
        # Блок форматирования словаря под datetime формат и проверки времени работы
        if ':' or '-' or ' ' not in result_dict['time']:
            end = int(result_dict['time']) + int(result_dict['hours'])
            result_dict['endtime'] = str(end)+':00:00'
            if end <= 23:
                pass
            else:
                print('Аренда выходит за рамки рабочего дня')
            result_dict['time'] = result_dict['time']+':00:00'
        return result_dict

    def get_summ(self, result_dict):
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
        print("BREAK")
        hours_counter = 0
        result_price = 0
        while hours_counter < hours:
            if start_time + hours_counter < pricing['splitter']:
                result_price += pricing['price'][0]
                hours_counter += 1
            else:
                result_price += pricing['price'][1]
                hours_counter += 1
        print(result_price)
        return result_price
