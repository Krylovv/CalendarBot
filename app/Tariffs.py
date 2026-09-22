import json
import os
import shutil
import threading

# Bundled initial values; the editable copy lives in ./data (mounted volume in Docker)
DEFAULT_PATH = "./tarification.json"
DATA_PATH = "./data/tarification.json"

DAY_TYPES = {
    "weekday": "Будни (пн–чт)",
    "friday": "Пятница",
    "weekend": "Выходные (сб–вс)",
}
FIELDS = ("splitter", "price_before", "price_after")

# Telegram thread writes while the sync thread reads
_lock = threading.Lock()


def _load():
    if not os.path.exists(DATA_PATH):
        os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
        shutil.copyfile(DEFAULT_PATH, DATA_PATH)
    with open(DATA_PATH) as f:
        return json.load(f)


def load() -> dict:
    with _lock:
        return _load()


def update(day: str, field: str, value: int) -> dict:
    with _lock:
        data = _load()
        if field == "splitter":
            data[day]["splitter"] = value
        elif field == "price_before":
            data[day]["price"][0] = value
        elif field == "price_after":
            data[day]["price"][1] = value
        else:
            raise ValueError(f"Unknown tariff field: {field}")
        # Atomic replace so readers never see a half-written file
        tmp_path = DATA_PATH + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, DATA_PATH)
        return data


def get_value(data: dict, day: str, field: str) -> int:
    if field == "splitter":
        return data[day]["splitter"]
    return data[day]["price"][0 if field == "price_before" else 1]


def format_tariffs(data: dict) -> str:
    text = "Тарифы, ₽/час\n"
    for day, title in DAY_TYPES.items():
        splitter = data[day]["splitter"]
        price_before, price_after = data[day]["price"]
        text += (
            f"\n{title}\n  до {splitter}:00 — {price_before}\n  с {splitter}:00 — {price_after}\n"
        )
    return text
