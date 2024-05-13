import logging
from io import BytesIO
from pathlib import Path
from typing import Sequence

import ballchasing
import discord
from replay_parser import ReplayParser
from replay_parser.models import Replay as ParsedReplay

from rsc.logs import GuildLogAdapter

logger = logging.getLogger("red.rsc.ballchasing.process")
log = GuildLogAdapter(logger)

# Disable debug logging in replay_parser (large amount of data)
logging.getLogger("replay_parser").setLevel(logging.INFO)


async def parse_replay(
    replay: discord.Attachment | str | bytes,
) -> ParsedReplay:
    # Initialize python replay parser
    parser = ReplayParser(debug=False)

    # Parse Replays first for validation
    if isinstance(replay, discord.Attachment):
        rdata = BytesIO(await replay.read())
    elif isinstance(replay, bytes):
        rdata = BytesIO(replay)
    elif isinstance(replay, str):
        # Read bytes from file
        fdata = Path(replay).read_bytes()
        rdata = BytesIO(fdata)
    parsed = parser.parse(replay_file=rdata, net_stream=False)
    return parsed


async def parse_replays(
    replay_files: Sequence[discord.Attachment | str | bytes],
) -> list[ParsedReplay]:
    # Initialize python replay parser
    parser = ReplayParser(debug=False)

    # Parse Replays first for validation
    parsed_replays: list[ParsedReplay] = []
    for rf in replay_files:
        if isinstance(rf, discord.Attachment):
            rdata = BytesIO(await rf.read())
        elif isinstance(rf, bytes):
            rdata = BytesIO(rf)
        elif isinstance(rf, str):
            # Read bytes from file
            fdata = Path(rf).read_bytes()
            rdata = BytesIO(fdata)
        parsed = parser.parse(replay_file=rdata, net_stream=False)
        parsed_replays.append(parsed)
    return parsed_replays


async def duplicate_player_scores(
    parsed_replay: ParsedReplay, bc_replay: ballchasing.models.Replay
) -> bool:
    parsed_players = parsed_replay.player_stats
    if not parsed_players:
        raise ValueError("A replay is missing player data.")

    blue_bc_players = []
    orange_bc_players = []
    if bc_replay.blue:
        blue_bc_players = bc_replay.blue.players
    if bc_replay.orange:
        orange_bc_players = bc_replay.orange.players

    if not (blue_bc_players and orange_bc_players):
        log.debug("Ballchasing replay has no player data.")
        return False

    matching_players: list[bool] = []
    for pplayer in parsed_players:
        # Player team. Parser returns 0 for blue. 1 for orange
        pplayer_team: str | None = pplayer.get("Team")
        log.debug(f"PPlayer Team: {pplayer_team}")
        if pplayer_team is None:
            raise ValueError("Player has no team in replay data.")

        pplayer_platform: str | None = pplayer.get("Platform")
        if pplayer_platform is None:
            raise ValueError("Player has no platform data in replay data.")

        pplayer_platform = pplayer_platform.lower().replace("OnlinePlatform_", "")
        log.debug(f"PPlayer Platform: {pplayer_platform}")

        # Speed up processing by only iterating correct team
        match = False
        if pplayer_team == 0:
            for blueplayer in blue_bc_players:
                # Make sure replay has stats
                if not (
                    blueplayer.stats
                    and blueplayer.stats.core
                    and blueplayer.stats.core.score is not None
                    and blueplayer.stats.core.goals is not None
                    and blueplayer.stats.core.assists is not None
                    and blueplayer.stats.core.saves is not None
                    and blueplayer.stats.core.shots is not None
                ):
                    raise ValueError("Ballchasing replay has no stats data.")

                # Check for matching name
                pplayer_name = pplayer.get("Name")
                log.debug(f"PPlayer Name: {pplayer_name} BC Name: {blueplayer.name}")
                if pplayer_name != blueplayer.name:
                    continue

                # Check for matching score
                pplayer_score = pplayer.get("Score")
                log.debug(
                    f"PPlayer Score: {pplayer_score} BC Score: {blueplayer.stats.core.score}"
                )
                if pplayer_score != blueplayer.stats.core.score:
                    continue

                # Check for matching goals
                pplayer_goals = pplayer.get("Goals")
                log.debug(
                    f"PPlayer Goals: {pplayer_goals} BC Goals: {blueplayer.stats.core.goals}"
                )
                if pplayer_goals != blueplayer.stats.core.goals:
                    continue

                # Check for matching assists
                pplayer_assists = pplayer.get("Assists")
                log.debug(
                    f"PPlayer Assists: {pplayer_assists} BC Assists: {blueplayer.stats.core.assists}"
                )
                if pplayer_assists != blueplayer.stats.core.assists:
                    continue

                # Check for matching saves
                pplayer_saves = pplayer.get("Saves")
                log.debug(
                    f"PPlayer Saves: {pplayer_saves} BC Saves: {blueplayer.stats.core.saves}"
                )
                if pplayer_saves != blueplayer.stats.core.saves:
                    continue

                # Check for matching shots
                pplayer_shots = pplayer.get("Shots")
                log.debug(
                    f"PPlayer Shots: {pplayer_shots} BC Shots: {blueplayer.stats.core.shots}"
                )
                if pplayer_shots != blueplayer.stats.core.shots:
                    continue

                log.debug(f"Found matching player stats: {pplayer_name}")
                match = True
        elif pplayer_team == 1:
            for orangeplayer in orange_bc_players:
                # Make sure replay has stats
                if not (
                    orangeplayer.stats
                    and orangeplayer.stats.core
                    and orangeplayer.stats.core.score is not None
                    and orangeplayer.stats.core.goals is not None
                    and orangeplayer.stats.core.assists is not None
                    and orangeplayer.stats.core.saves is not None
                    and orangeplayer.stats.core.shots is not None
                ):
                    raise ValueError("Ballchasing replay has no stats data.")

                # Check for matching name
                pplayer_name = pplayer.get("Name")
                log.debug(f"PPlayer Name: {pplayer_name} BC Name: {orangeplayer.name}")
                if pplayer_name != orangeplayer.name:
                    continue

                # Check for matching score
                pplayer_score = pplayer.get("Score")
                log.debug(
                    f"PPlayer Score: {pplayer_score} BC Score: {orangeplayer.stats.core.score}"
                )
                if pplayer_score != orangeplayer.stats.core.score:
                    continue

                # Check for matching goals
                pplayer_goals = pplayer.get("Goals")
                log.debug(
                    f"PPlayer Goals: {pplayer_goals} BC Goals: {orangeplayer.stats.core.goals}"
                )
                if pplayer_goals != orangeplayer.stats.core.goals:
                    continue

                # Check for matching assists
                pplayer_assists = pplayer.get("Assists")
                log.debug(
                    f"PPlayer Assists: {pplayer_assists} BC Assists: {orangeplayer.stats.core.assists}"
                )
                if pplayer_assists != orangeplayer.stats.core.assists:
                    continue

                # Check for matching saves
                pplayer_saves = pplayer.get("Saves")
                log.debug(
                    f"PPlayer Saves: {pplayer_saves} BC Saves: {orangeplayer.stats.core.saves}"
                )
                if pplayer_saves != orangeplayer.stats.core.saves:
                    continue

                # Check for matching shots
                pplayer_shots = pplayer.get("Shots")
                log.debug(
                    f"PPlayer Shots: {pplayer_shots} BC Shots: {orangeplayer.stats.core.shots}"
                )
                if pplayer_shots != orangeplayer.stats.core.shots:
                    continue

                log.debug(f"Found matching player stats: {pplayer_name}")
                match = True
        else:
            log.debug(f"Unknown player team: {pplayer}")
            continue

        matching_players.append(match)

    # If we have 100% matching players, return True
    if all(m for m in matching_players):
        return True
    return False


async def replay_group_collisions(
    replay_files: Sequence[discord.Attachment | str | bytes],
    bc_replays: list[ballchasing.models.Replay],
) -> list[discord.Attachment | str | bytes]:
    # Parse replays locally. Use dict to track original identifier
    parsed_replays: dict[discord.Attachment | str | bytes, ParsedReplay] = {}
    for r in replay_files:
        parsed_replays[r] = await parse_replay(replay=r)

    collisions: list[discord.Attachment | str | bytes] = []
    for bcreplay in bc_replays:
        log.debug(f"{'='*20} BC Replay - {bcreplay.id} {'='*20}")
        for identifier, preplay in parsed_replays.items():
            log.debug(f"BC Map: {bcreplay.map_code} Parsed Map: {preplay.map_code}")
            # Check map name
            if (
                bcreplay.map_code
                and preplay.map_code
                and bcreplay.map_code.lower() != preplay.map_code.lower()
            ):
                continue

            if not await duplicate_player_scores(
                parsed_replay=preplay, bc_replay=bcreplay
            ):
                continue

            # Found collision. Track and move on
            log.debug("Found duplicate.")
            collisions.append(identifier)
            break
    return collisions
