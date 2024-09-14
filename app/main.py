from Bot import Bot
from threading import Thread
from Spreadsheet import Spreadsheets


def main():
    bot = Bot()
    sh = Spreadsheets()
    Thread(target=bot.bot_func).start()
    Thread(target=sh.spreadsheet_to_calendar).start()


if __name__ == "__main__":
    main()
