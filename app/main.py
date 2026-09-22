from threading import Thread

from Bot import Bot
from Spreadsheet import Spreadsheets


def main():
    bot = Bot()
    # The bot reports new bookings and sync problems to authorized users
    sh = Spreadsheets(notifier=bot)
    Thread(target=bot.bot_func).start()
    Thread(target=sh.spreadsheet_to_calendar).start()


if __name__ == "__main__":
    main()
