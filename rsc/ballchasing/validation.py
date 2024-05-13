import difflib
import logging
from hashlib import md5

import ballchasing
import discord
from rscapi.models.match import Match

from rsc.enums import MatchFormat

log = logging.getLogger("red.rsc.ballchasing.validation")


async def duplicate_replay_hashes(replays: list[discord.Attachment]) -> bool:
    """Check discord.Attachment replay list for matching md5 hashes"""
    hashes = []
    for r in replays:
        data = await r.read()
        h = md5(data).hexdigest()
        log.debug(f"Replay Hash: {h}")
        if h in hashes:
            return True
        else:
            hashes.append(h)
    return False


async def is_replay_file(replay: discord.Attachment) -> bool:
    """Check if file provided is a replay file"""
    if replay.filename.endswith(".replay"):
        return True
    return False


async def check_team_type_match(home: str, away: str, match: Match) -> bool:
    """Check if home and away team are correct"""
    if not (match.home_team.name and match.away_team.name):
        return False

    if home.lower() != match.home_team.name.lower():
        return False

    if away.lower() != match.away_team.name.lower():
        return False
    return True


async def match_already_complete(match: Match) -> bool:
    """Check if `Match` has been completed and recorded"""
    if not match.results:
        return False

    if not (
        hasattr(match.results, "home_wins") and hasattr(match.results, "away_wins")
    ):
        return False

    if not (match.results.home_wins and match.results.away_wins):
        return False

    if (match.results.home_wins + match.results.away_wins) != match.num_games:
        return False
    return True


async def minimum_games_required(match: Match) -> int:
    match match.match_format:
        case MatchFormat.GAME_SERIES:
            if not match.num_games:
                raise ValueError("API Match does not have number of games set.")
            return match.num_games
        case MatchFormat.BEST_OF_THREE:
            return 2
        case MatchFormat.BEST_OF_FIVE:
            return 3
        case MatchFormat.BEST_OF_SEVEN:
            return 4
        case _:
            raise ValueError(f"Unknown Match Format: {match.match_format}")


async def validate_team_names(match: Match, replay: ballchasing.models.Replay) -> bool:
    home = match.home_team.name
    away = match.away_team.name

    if not (home and away):
        return False

    valid = (home.lower(), away.lower())

    if not (replay.blue and replay.orange):
        return False

    if not (replay.blue.name and replay.orange.name):
        return False

    log.debug(f"Blue: {replay.blue.name} Orange: {replay.orange.name}")

    if replay.blue.name.lower() in valid and replay.orange.name.lower() in valid:
        log.debug("Valid team names")
        return True

    # Similarity check (Levenshtein ratio)
    # Check both team names since people do dumb things
    home_lev1 = difflib.SequenceMatcher(
        None, valid[0], replay.blue.name.lower()
    ).ratio()
    home_lev2 = difflib.SequenceMatcher(
        None, valid[0], replay.orange.name.lower()
    ).ratio()

    away_lev1 = difflib.SequenceMatcher(
        None, valid[1], replay.blue.name.lower()
    ).ratio()
    away_lev2 = difflib.SequenceMatcher(
        None, valid[1], replay.orange.name.lower()
    ).ratio()

    log.debug(
        f"Levehstein Ratios. Home: {home_lev1:.3f} {home_lev2:.3f} Away: {away_lev1:.3f} {away_lev2:.3f}"
    )
    lev_threshold = 0.9
    if (home_lev1 > lev_threshold or home_lev2 > lev_threshold) and (
        away_lev1 > lev_threshold or away_lev2 > lev_threshold
    ):
        log.debug("Team names are close enough to threshold.")
        return True

    return False
