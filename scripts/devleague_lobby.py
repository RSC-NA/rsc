#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import requests

DATA_PATH = Path(__file__).resolve().parent.parent / "data/devleague"


def load_json(name: str) -> dict:
    json_path = DATA_PATH / name
    print(f"JSON Path: {json_path}")

    with json_path.open() as fd:
        return json.load(fd)


def start(guild_id: int):
    data = load_json("devleague_webhook.json")

    for lobby in data.values():
        lobby["guild_id"] = str(guild_id)

    print(f"Sending mock dev league game data for guild {guild_id}...")
    resp = requests.post("http://localhost:8008/devleague_match", json=data, timeout=10)
    print(f"Response Status: {resp.status_code}")


def teardown(guild_id: int, match_id: int):
    data = load_json("devleague_event_game_finished.json")

    data["match_id"] = match_id
    data["guild_id"] = str(guild_id)

    print(f"Sending mock dev league finished event for match {match_id} in guild {guild_id}...")
    resp = requests.post("http://localhost:8008/devleague_event", json=data, timeout=10)
    print(f"Response Status: {resp.status_code}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test dev league lobby webhooks")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Send the sample dev league lobbies")
    start_parser.add_argument("guild_id", type=int, help="Guild ID to send the lobbies to")

    teardown_parser = subparsers.add_parser("teardown", help="End a dev league match")
    teardown_parser.add_argument("guild_id", type=int, help="Guild ID the match is in")
    teardown_parser.add_argument("match_id", type=int, help="Match ID to end")

    argv = parser.parse_args()

    if argv.command == "start":
        start(guild_id=argv.guild_id)
    else:
        teardown(guild_id=argv.guild_id, match_id=argv.match_id)
