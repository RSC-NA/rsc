#!/usr/bin/env python3

import json
import os
from pathlib import Path

import requests


def send_webhook():
    script_path = os.path.dirname(os.path.abspath(__file__))
    print(f"Script path: {script_path}")

    json_path = Path(script_path).parent
    json_path = json_path / "json_examples/combines/combines_webhook.json"
    print(f"JSON Path: {json_path.absolute}")

    with open(json_path, "r") as fd:
        data = json.load(fd)

    print("Sending mock combine data...")
    resp = requests.post("http://localhost:8008/combines_match", json=data, timeout=10)
    print(f"Response Status: {resp.status_code}")


if __name__ == "__main__":
    send_webhook()
