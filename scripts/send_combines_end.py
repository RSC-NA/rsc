#!/usr/bin/env python3

import argparse
import json
import os
from pathlib import Path

import requests


def send_finished(lobby_id: int):
    script_path = os.path.dirname(os.path.abspath(__file__))
    print(f"Script path: {script_path}")

    json_path = Path(script_path).parent
    json_path = json_path / "data/combines/combines_event_game_finished.json"
    print(f"JSON Path: {json_path.absolute}")

    with open(json_path, "r") as fd:
        data = json.load(fd)

    data["match_id"] = lobby_id

    print("Sending mock combine data...")
    resp = requests.post("http://localhost:8008/combines_event", json=data, timeout=10)
    print(f"Response Status: {resp.status_code}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="End combine lobby")
    parser.add_argument("lobby_id", type=int, help="Lobby ID to end")
    argv = parser.parse_args()

    send_finished(argv.lobby_id)
