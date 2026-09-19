"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. See README.md → "Endpoints" for the full function list.
"""
import json
import os

from cricbuzz.matches import get_live, get_scorecard
from cricbuzz.players import get_details as get_player_details

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # every match being played right now, grouped by competition
    save("live_matches.json", get_live())

    # a match id, or any cricbuzz.com match link — this is the IPL 2026 final
    save("scorecard_155409.json", get_scorecard(155409))

    # a player id, or any cricbuzz.com profile link — this is Virat Kohli
    save("player_1413.json", get_player_details(1413))
