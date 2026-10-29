#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

import requests

DATA_PATH = Path(__file__).resolve().parent.parent / "data/combines"


def load_json(name: str) -> dict:
    json_path = DATA_PATH / name
    print(f"JSON Path: {json_path}")

    with json_path.open() as fd:
        return json.load(fd)


def start(guild_id: int, twos: bool = False):
    data = load_json("combines_webhook_2s.json" if twos else "combines_webhook.json")

    for lobby in data.values():
        lobby["guild_id"] = str(guild_id)

    print(f"Sending mock combine data for guild {guild_id}...")
    resp = requests.post("http://localhost:8008/combines_match", json=data, timeout=10)
    print(f"Response Status: {resp.status_code}")


def teardown(guild_id: int, lobby_id: int):
    data = load_json("combines_event_game_finished.json")

    data["match_id"] = lobby_id
    data["guild_id"] = str(guild_id)

    print(f"Sending mock combine finished event for lobby {lobby_id} in guild {guild_id}...")
    resp = requests.post("http://localhost:8008/combines_event", json=data, timeout=10)
    print(f"Response Status: {resp.status_code}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test combines lobby webhooks")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Send the sample combine lobbies")
    start_parser.add_argument("guild_id", type=int, help="Guild ID to send the lobbies to")
    start_parser.add_argument("-2", dest="twos", action="store_true", default=False, help="Send 2s league event")

    teardown_parser = subparsers.add_parser("teardown", help="End a combine lobby")
    teardown_parser.add_argument("guild_id", type=int, help="Guild ID the lobby is in")
    teardown_parser.add_argument("lobby_id", type=int, help="Lobby ID to end")

    argv = parser.parse_args()

    if argv.command == "start":
        start(guild_id=argv.guild_id, twos=argv.twos)
    else:
        teardown(guild_id=argv.guild_id, lobby_id=argv.lobby_id)
