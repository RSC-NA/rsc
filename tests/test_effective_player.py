from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from rscapi.models.error_code_enum import ErrorCodeEnum
from rscapi.models.intent_to_play import IntentToPlay
from rscapi.models.league_player import LeaguePlayer
from rscapi.models.league_player_member import LeaguePlayerMember
from rscapi.models.league_player_status_enum import LeaguePlayerStatusEnum
from rscapi.models.member_intent import MemberIntent
from rscapi.models.member_intent_data import MemberIntentData
from rscapi.models.season import Season

from rsc.exceptions import ApiError, NotFoundError, ServerError
from rsc.leagues.effective import is_playing, pick_effective_row
from rsc.leagues.leagues import LeagueMixIn

from .utils import api_error, raw_api_exception

S27 = Season.model_construct(id=11, number=27, end_date=datetime(2026, 11, 22, tzinfo=UTC))
S28 = Season.model_construct(id=12, number=28, end_date=datetime(2027, 4, 4, tzinfo=UTC))
SEASONS = [S27, S28]

S27_BEING_PLAYED = datetime(2026, 11, 20, tzinfo=UTC)
S27_ENDED = datetime(2026, 11, 23, tzinfo=UTC)

MEMBER = 111


def _row(season: Season, status: str, discord_id: int = MEMBER) -> LeaguePlayer:
    return LeaguePlayer.model_construct(
        season=season.number,
        status=LeaguePlayerStatusEnum(status),
        player=LeaguePlayerMember(name="someone", discord_id=discord_id),
    )


def _intent(discord_id: int, *, missing: bool, returning: bool) -> IntentToPlay:
    player = MemberIntent(player=MemberIntentData(rsc_name="someone", discord_id=discord_id))
    return IntentToPlay(season=28, missing=missing, returning=returning, player=player)


class TestPickEffectiveRow:
    def test_a_rostered_row_holds_until_its_season_ends(self):
        old, new = _row(S27, "RO"), _row(S28, "FA")

        assert pick_effective_row([new, old], SEASONS, S27_BEING_PLAYED, signups_open=True) is old

    def test_the_newest_row_wins_once_the_older_season_has_ended(self):
        old, new = _row(S27, "RO"), _row(S28, "FA")

        assert pick_effective_row([old, new], SEASONS, S27_ENDED, signups_open=True) is new

    def test_the_older_row_holds_for_a_member_who_has_not_declared_while_sign_ups_are_open(self):
        old = _row(S27, "RO")

        assert pick_effective_row([old], SEASONS, S27_ENDED, signups_open=True) is old

    def test_a_member_with_no_rows_is_non_playing(self):
        assert pick_effective_row([], SEASONS, S27_ENDED, signups_open=True) is None

    def test_the_older_row_stops_counting_when_sign_ups_close(self):
        old = _row(S27, "RO")

        assert pick_effective_row([old], SEASONS, S27_ENDED, signups_open=False) is None

    def test_a_declared_not_returning_member_is_non_playing(self):
        old = _row(S27, "RO")

        assert pick_effective_row([old], SEASONS, S27_ENDED, signups_open=True, not_returning=True) is None

    def test_a_not_returning_member_stays_rostered_until_their_season_ends(self):
        old = _row(S27, "RO")

        assert pick_effective_row([old], SEASONS, S27_BEING_PLAYED, signups_open=True, not_returning=True) is old

    def test_a_row_in_the_only_season_read_is_the_newest_row(self):
        only = _row(S28, "DE")

        assert pick_effective_row([only], [S28], S27_ENDED, signups_open=False) is only

    @pytest.mark.parametrize(
        ("old_status", "new_status", "season_while_s27_is_played"),
        [
            ("RO", "RO", S27),
            ("RO", "FA", S27),
            ("FA", "FA", S28),
            ("PF", "DE", S28),
            ("RO", "UG", S27),
            ("PW", "DE", S28),
            ("IR", "FA", S27),
            ("UG", "UG", S27),
            ("DR", "DE", S28),
            ("RO", "PW", S27),
            ("IR", "RO", S27),
            ("FR", "DE", S28),
            ("AR", "AR", S27),
        ],
    )
    def test_members_with_a_row_in_both_seasons(self, old_status, new_status, season_while_s27_is_played):
        rows = [_row(S27, old_status), _row(S28, new_status)]

        before = pick_effective_row(rows, SEASONS, S27_BEING_PLAYED, signups_open=True)
        after = pick_effective_row(rows, SEASONS, S27_ENDED, signups_open=True)

        assert before is not None
        assert before.season == season_while_s27_is_played.number
        assert after is rows[1]


class TestIsPlaying:
    @pytest.mark.parametrize("status", ["DR", "FR", "BN"])
    def test_a_dropped_former_or_banned_row_is_not_playing(self, status):
        assert not is_playing(_row(S27, status))

    def test_no_row_is_not_playing(self):
        assert not is_playing(None)

    @pytest.mark.parametrize("status", ["RO", "FA", "DE", "PF", "UG"])
    def test_any_other_row_is_playing(self, status):
        assert is_playing(_row(S28, status))


def _mixin(*, default: Season, signup: Season | Exception | None, rows: list[LeaguePlayer], intents: list[IntentToPlay] | None = None):
    saved = LeagueMixIn.__abstractmethods__
    LeagueMixIn.__abstractmethods__ = frozenset()
    try:
        mixin = object.__new__(LeagueMixIn)
    finally:
        LeagueMixIn.__abstractmethods__ = saved

    numbers = {s.id: s.number for s in SEASONS}

    def paged_players(guild, season=None):
        async def page():
            for row in rows:
                if row.season == numbers[season or default.id]:
                    yield row

        return page()

    async def players(guild, discord_id=None, season=None, limit=0):
        return [r for r in rows if r.player.discord_id == discord_id and r.season == numbers[season or default.id]]

    async def seasons(guild, number=None):
        return [s for s in SEASONS if s.number == number]

    async def player_intents(guild, season_id, returning=None, missing=None, discord_id=None):
        return [i for i in intents or [] if discord_id is None or (i.player and i.player.player.discord_id == discord_id)]

    mixin.current_season = AsyncMock(return_value=default)
    mixin.next_signup_season = AsyncMock(side_effect=signup) if isinstance(signup, Exception) else AsyncMock(return_value=signup)
    mixin.seasons = AsyncMock(side_effect=seasons)
    mixin.player_intents = AsyncMock(side_effect=player_intents)
    mixin.paged_players = MagicMock(side_effect=paged_players)
    mixin.players = AsyncMock(side_effect=players)
    return mixin


async def _effective(mixin) -> dict[int, LeaguePlayer]:
    return {row.player.discord_id: row async for row in mixin.effective_players(MagicMock())}


class TestEffectivePlayers:
    async def test_a_member_with_only_an_older_row_is_kept_while_sign_ups_are_open(self):
        old = _row(S27, "RO")
        mixin = _mixin(default=S28, signup=S28, rows=[old])

        assert await _effective(mixin) == {MEMBER: old}

    async def test_the_new_season_row_replaces_the_older_one(self):
        old, new = _row(S27, "RO"), _row(S28, "FA")
        mixin = _mixin(default=S28, signup=S28, rows=[old, new])

        assert await _effective(mixin) == {MEMBER: new}

    async def test_a_declared_not_returning_member_is_left_out(self):
        leaving, pending = _row(S27, "RO", discord_id=1), _row(S27, "RO", discord_id=2)
        mixin = _mixin(default=S28, signup=S28, rows=[leaving, pending], intents=[_intent(1, missing=False, returning=False)])

        assert await _effective(mixin) == {2: pending}

    async def test_an_intent_row_marked_missing_is_not_a_declaration(self):
        old = _row(S27, "RO")
        mixin = _mixin(default=S28, signup=S28, rows=[old], intents=[_intent(MEMBER, missing=True, returning=False)])

        assert await _effective(mixin) == {MEMBER: old}

    @pytest.mark.parametrize(
        "closed",
        [
            api_error(404, "Signups are closed. No upcoming season is currently accepting signups.", code=ErrorCodeEnum.NO_SIGNUP_SEASON),
            api_error(405, "Signups are closed", code=ErrorCodeEnum.SIGNUPS_CLOSED),
            None,
        ],
        ids=["404", "405", "none"],
    )
    async def test_only_the_default_season_counts_once_sign_ups_close(self, closed):
        old, new = _row(S27, "RO", discord_id=1), _row(S28, "RO", discord_id=2)
        mixin = _mixin(default=S28, signup=closed, rows=[old, new])

        assert await _effective(mixin) == {2: new}

    async def test_another_api_failure_is_not_read_as_closed_sign_ups(self):
        mixin = _mixin(default=S28, signup=api_error(500, "Down"), rows=[_row(S27, "RO")])

        with pytest.raises(ServerError):
            await _effective(mixin)

    @pytest.mark.parametrize(
        "other_404",
        [
            api_error(404, "League is not in database, you may have the wrong ID.", code=ErrorCodeEnum.NOT_FOUND),
            ApiError.from_exception(raw_api_exception(404, "<html><body>404 Not Found</body></html>")),
        ],
        ids=["unknown league", "proxy page"],
    )
    async def test_any_other_404_is_not_read_as_closed_sign_ups(self, other_404):
        mixin = _mixin(default=S28, signup=other_404, rows=[_row(S27, "RO")])

        with pytest.raises(NotFoundError):
            await _effective(mixin)

    async def test_both_seasons_are_read_while_the_older_one_is_still_the_default(self):
        rostered, drafted = _row(S27, "RO", discord_id=1), _row(S28, "DE", discord_id=2)
        mixin = _mixin(default=S27, signup=S28, rows=[rostered, drafted])

        assert await _effective(mixin) == {1: rostered, 2: drafted}


class TestEffectivePlayer:
    async def test_matches_the_row_the_full_read_picks(self):
        old, new, pending = _row(S27, "RO"), _row(S28, "FA"), _row(S27, "RO", discord_id=2)
        mixin = _mixin(default=S28, signup=S28, rows=[old, new, pending])

        assert await mixin.effective_player(MagicMock(), MEMBER) is new
        assert await mixin.effective_player(MagicMock(), 2) is pending

    async def test_a_declared_not_returning_member_has_no_row(self):
        mixin = _mixin(default=S28, signup=S28, rows=[_row(S27, "RO")], intents=[_intent(MEMBER, missing=False, returning=False)])

        assert await mixin.effective_player(MagicMock(), MEMBER) is None

    async def test_another_members_declaration_does_not_count(self):
        pending = _row(S27, "RO")
        mixin = _mixin(default=S28, signup=S28, rows=[pending], intents=[_intent(2, missing=False, returning=False)])

        assert await mixin.effective_player(MagicMock(), MEMBER) is pending
        assert mixin.player_intents.await_args.kwargs["discord_id"] == MEMBER

    async def test_a_member_with_no_row_in_any_season_has_no_row(self):
        mixin = _mixin(default=S28, signup=S28, rows=[])

        assert await mixin.effective_player(MagicMock(), MEMBER) is None

    async def test_a_404_for_an_unknown_league_is_not_read_as_closed_sign_ups(self):
        unknown_league = api_error(404, "League is not in database, you may have the wrong ID.", code=ErrorCodeEnum.NOT_FOUND)
        mixin = _mixin(default=S28, signup=unknown_league, rows=[_row(S27, "RO")])

        with pytest.raises(NotFoundError):
            await mixin.effective_player(MagicMock(), MEMBER)
