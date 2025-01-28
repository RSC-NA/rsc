import logging
from datetime import UTC, datetime, timedelta

from rscapi.models import Match

log = logging.getLogger("red.rsc.ballchasing.search")


async def get_bc_date_range(match: Match) -> tuple[datetime, datetime]:
    """Return ballchasing match time search range"""
    if not match.var_date:
        raise ValueError("Match has no date attribute.")
    match_date = match.var_date
    log.debug(f"BC Match Date: {match_date}")
    after = match_date.replace(hour=21, minute=55, second=0).astimezone(tz=UTC)
    before = match_date.replace(hour=23, minute=59, second=0).astimezone(tz=UTC)
    return after, before


async def get_match_date_range(date: datetime) -> tuple[datetime, datetime]:
    """Return a tuple of datetime objects that has a search range for specified date"""
    date_gt = date - timedelta(minutes=1)
    date_lt = date.replace(hour=23, minute=59, second=59)
    return (date_gt, date_lt)
