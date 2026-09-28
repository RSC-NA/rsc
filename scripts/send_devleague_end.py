#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import requests


def send_finished(match_id: int):
    json_path = Path(__file__).resolve().parent.parent / "data/devleague/devleague_event_game_finished.json"
    print(f"JSON Path: {json_path}")

    with open(json_path) as fd:
        data = json.load(fd)

    data["match_id"] = match_id

    print("Sending mock dev league finished event...")
    resp = requests.post("http://localhost:8008/devleague_event", json=data, timeout=10)
    print(f"Response Status: {resp.status_code}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="End dev league match")
    parser.add_argument("match_id", type=int, help="Match ID to end")
    argv = parser.parse_args()

    send_finished(argv.match_id)
