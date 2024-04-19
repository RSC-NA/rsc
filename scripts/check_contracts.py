#!/usr/bin/env python3

import argparse
import os
import sys
from pathlib import Path
from pprint import pprint

import pandas
import requests

API_KEY = os.environ.get("RSC_API_KEY")
API_HOST = "https://api.rscna.com/api/v1"

auth = {"Authorization": f"Api-Key: {API_KEY}"}
session = requests.session()
session.headers.update(auth)


def api_fa_players():
    r = session.get(
        "https://api.rscna.com/api/v1/league-players/?status=FA&limit=10000"
    )

    if r.status_code != 200:
        raise RuntimeError("Error fetching franchises from RSC API")
    data = r.json()
    return data["results"]


def check_invalid_fa(players, df: pandas.DataFrame):
    invalid = []
    for player in players:
        fa = df[
            df["Player Name"].str.fullmatch(
                player["player"]["name"], na=False, case=False
            )
        ]
        if not fa.empty:
            # print(f"Invalid FA: {fa['Player Name'].item()}")
            invalid.append(fa["Player Name"].item())
    return invalid


def remove_cut_players(players):
    r = session.get(
        "https://api.rscna.com/api/v1/transactions/history/?season_number=20&league=1&transaction_type=CUT&limit=5000"
    )

    if r.status_code != 200:
        raise RuntimeError("Error fetching franchises from RSC API")
    data = r.json()

    cut_players = []
    for r in data["results"]:
        tmp = r["player_updates"].pop(0)
        try:
            cut_players.append(tmp["player"]["player"]["name"])
        except Exception as exc:
            pprint(tmp)
            raise exc

    final = []
    for player in players:
        add = True
        for cut in cut_players:
            if player.lower() == cut.lower():
                add = False
                break
        if add:
            final.append(player)

    return final


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Check contracts for inconsistencies")
    parser.add_argument("csvfile", help="Path to CSV version of last seasons contracts")
    argv = parser.parse_args()

    if not Path(argv.csvfile).is_file():
        print(f"{argv.csvfile} does not exist.")
        sys.exit(1)

    df = pandas.read_csv(argv.csvfile)
    print(df)

    players = api_fa_players()

    two_season_contracts = df[df["Contract Length"] == 2]
    invalid_fa = check_invalid_fa(players, two_season_contracts)
    print(f"Len FA unfiltered: {len(invalid_fa)}")

    final_fa_invalid = remove_cut_players(invalid_fa)
    print(f"Invalid FA len: {len(final_fa_invalid)}")
    for fa in final_fa_invalid:
        print(f"Invalid FA: {fa}")
