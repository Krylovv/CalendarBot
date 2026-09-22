import json
import sys
import tempfile
from pathlib import Path

# The app modules import each other as top-level modules (python3 app/main.py)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import Tariffs  # noqa: E402

TARIFFS = {
    "weekday": {"splitter": 18, "price": [4000, 4500]},
    "friday": {"splitter": 18, "price": [4000, 5000]},
    "weekend": {"splitter": 16, "price": [4500, 5000]},
}


def use_tariffs(testcase, tariffs=TARIFFS):
    # Point Tariffs at a throwaway copy so tests never touch ./data
    folder = tempfile.TemporaryDirectory()
    testcase.addCleanup(folder.cleanup)
    default_path = Path(folder.name) / "tarification.json"
    default_path.write_text(json.dumps(tariffs))
    old_paths = Tariffs.DEFAULT_PATH, Tariffs.DATA_PATH
    Tariffs.DEFAULT_PATH = str(default_path)
    Tariffs.DATA_PATH = str(Path(folder.name) / "data" / "tarification.json")

    def restore():
        Tariffs.DEFAULT_PATH, Tariffs.DATA_PATH = old_paths

    testcase.addCleanup(restore)


def timed_event(start, end, summary="Иван", description=None, private=None, event_id="e1"):
    event = {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if description is not None:
        event["description"] = description
    if private is not None:
        event["extendedProperties"] = {"private": private}
    return event
