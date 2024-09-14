FROM python:alpine

WORKDIR /opt

# Убрать копирование секретов
COPY ./app ./app
COPY ./req.txt .

RUN python3 -m pip install -r req.txt

CMD python3 app/main.py