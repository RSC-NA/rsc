#!/usr/bin/env python3

import json
from pathlib import Path

import requests


def send_webhook():
    json_path = Path(__file__).resolve().parent.parent / "data/devleague/devleague_webhook.json"
    print(f"JSON Path: {json_path}")

    with open(json_path) as fd:
        data = json.load(fd)

    print("Sending mock dev league game data...")
    resp = requests.post("http://localhost:8008/devleague_match", json=data, timeout=10)
    print(f"Response Status: {resp.status_code}")


if __name__ == "__main__":
    send_webhook()
