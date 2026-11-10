#!/usr/bin/env python3

import argparse
import copy
import json
import math
import time
from pathlib import Path

import requests

# The only player given a Discord ID: pinged on the card and sent the DM. Everyone else
# has none, as when the site can't match them, so testing never pings real players.
TEST_DISCORD_ID = 138778232802508801

DATA_PATH = Path(__file__).resolve().parent.parent / "data/devleague"


def load_json(name: str) -> dict:
    json_path = DATA_PATH / name
    print(f"JSON Path: {json_path}")

    with json_path.open() as fd:
        return json.load(fd)


def games_arg(value: str) -> int:
    games = int(value)
    if games < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return games


def with_games(data: dict, games: int) -> dict:
    """`games` lobbies made by cycling through the sample ones, numbered on from the first sample ID."""
    samples = list(data.values())
    first_id = min(lobby["id"] for lobby in samples)
    lobbies = {}
    for i in range(games):
        lobby = copy.deepcopy(samples[i % len(samples)])
        lobby["id"] = first_id + i
        for player in [*lobby["home"], *lobby["away"]]:
            player["match_id"] = lobby["id"]
        lobbies[str(lobby["id"])] = lobby
    return lobbies


def start(guild_id: int, games: int | None = None, presses: int = 1, interval: float = 3, discord_id: int = TEST_DISCORD_ID):
    data = load_json("devleague_webhook.json")
    if games:
        data = with_games(data, games)

    for lobby in data.values():
        lobby["guild_id"] = str(guild_id)
        for player in [*lobby["home"], *lobby["away"]]:
            player["discord_id"] = None
        lobby["home"][0]["discord_id"] = str(discord_id)

    # Like the website: each press sends every game so far, including ones already sent
    ids = list(data)
    for press in range(1, presses + 1):
        sent = ids[: math.ceil(len(ids) * press / presses)]
        print(f"Press {press}/{presses}: sending {len(sent)} mock dev league matches for guild {guild_id}: {', '.join(sent)}")
        resp = requests.post("http://localhost:8008/devleague_match", json={k: data[k] for k in sent}, timeout=10)
        print(f"Response Status: {resp.status_code}")
        if press < presses:
            time.sleep(interval)


def open_ids(guild_id: int) -> list[int]:
    """Every match the bot still has open in the guild: queued, with a live card, or with channels up."""
    resp = requests.get("http://localhost:8008/devleague_open", params={"guild_id": guild_id}, timeout=10)
    resp.raise_for_status()
    return resp.json()["lobbies"]


def teardown(guild_id: int, match_id: int | None):
    """End one match, or with no ID every open match, by sending the website's finished event."""
    ids = [match_id] if match_id is not None else open_ids(guild_id)
    if not ids:
        print(f"No open dev league matches in guild {guild_id}")
        return

    for one in ids:
        data = load_json("devleague_event_game_finished.json")
        data["match_id"] = one
        data["guild_id"] = str(guild_id)
        print(f"Sending mock dev league finished event for match {one} in guild {guild_id}...")
        resp = requests.post("http://localhost:8008/devleague_event", json=data, timeout=10)
        print(f"Response Status: {resp.status_code}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test dev league lobby webhooks")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start_parser = subparsers.add_parser("start", help="Send the sample dev league lobbies")
    start_parser.add_argument("guild_id", type=int, help="Guild ID to send the lobbies to")
    start_parser.add_argument(
        "-g",
        "--games",
        type=games_arg,
        help="Number of matches to create, cycling through the sample ones with IDs counting up from the first. Default: the sample as-is",
    )

    start_parser.add_argument(
        "-p",
        "--presses",
        type=games_arg,
        default=1,
        help="Send the webhook this many times, each with more of the games, like staff pressing the button again. Default: 1",
    )
    start_parser.add_argument(
        "-d",
        "--discord-id",
        type=int,
        default=TEST_DISCORD_ID,
        help=f"The lobby maker's Discord ID, the only player pinged and DMed. Default: {TEST_DISCORD_ID}",
    )
    start_parser.add_argument("-i", "--interval", type=float, default=3, help="Seconds between presses. Default: 3")

    teardown_parser = subparsers.add_parser("teardown", help="End a dev league match")
    teardown_parser.add_argument("guild_id", type=int, help="Guild ID the match is in")
    which = teardown_parser.add_mutually_exclusive_group(required=True)
    which.add_argument("match_id", type=int, nargs="?", help="Match ID to end")
    which.add_argument("-a", "--all", action="store_true", help="End every match the bot still has open in the guild")

    argv = parser.parse_args()

    if argv.command == "start":
        start(guild_id=argv.guild_id, games=argv.games, presses=argv.presses, interval=argv.interval, discord_id=argv.discord_id)
    else:
        teardown(guild_id=argv.guild_id, match_id=None if argv.all else argv.match_id)
