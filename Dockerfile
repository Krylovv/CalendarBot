# Pinned: req.txt pins (e.g. PyYAML 6.0.1) have no prebuilt wheels for newer Pythons on Alpine
FROM python:3.12-alpine

# Show print() output in `docker logs` immediately
ENV PYTHONUNBUFFERED=1

WORKDIR /opt

# Убрать копирование секретов
COPY ./app ./app
COPY ./tarification.json .
COPY ./req.txt .


RUN python3 -m pip install -r req.txt

CMD python3 app/main.py