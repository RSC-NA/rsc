#!/usr/bin/env python3

import argparse
import logging
import sys
from pathlib import Path

import requests

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

CHECKIN_URL = "https://devleague.rscna.com/c-api/check_in"


def combines_check_in(discord_id: int) -> int:
    log.info(f"Sending Check In: {discord_id}")
    params = {"discord_id": discord_id}
    r = requests.get(url=CHECKIN_URL, params=params, timeout=10)
    return r.status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Brute Force Break Blisters Shit")
    parser.add_argument("idfile", type=str, help="File containing Discord IDs")
    argv = parser.parse_args()

    fpath = Path(argv.idfile)

    if not fpath.is_file():
        log.error("Argument is not a valid file.")
        sys.exit(1)

    with fpath.open(mode="r") as fd:
        data = fd.readlines()

    if not data:
        log.error("No data in file")
        sys.exit(1)

    for i in data:
        try:
            combines_check_in(int(i))
        except Exception as exc:
            log.exception(f"Exception generated. DiscordID: {i}", exc_info=exc)
            sys.exit(2)
