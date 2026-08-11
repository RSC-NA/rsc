from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import discord
import pytest
from rscapi.exceptions import ApiException

from rsc.enums import MatchFormat, MatchTeamEnum, MatchType, Status
from rsc.exceptions import RscException
from rsc.matches.matches import MatchMixIn

GUILD_ID = 395806681994493964


def _create_mixin(**attrs):
    saved = MatchMixIn.__abstractmethods__
    MatchMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(MatchMixIn)
    finally:
        MatchMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _make_match_player(discord_id=111, name="Player1", captain=False, status=Status.ROSTERED, sub_status=None):
    p = MagicMock()
    p.discord_id = discord_id
    p.name = name
    p.captain = captain
    p.status = status
    p.sub_status = sub_status
    return p


def _make_match(
    home_team_name="Alpha",
    away_team_name="Bravo",
    home_players=None,
    away_players=None,
    home_gm_id=900,
    away_gm_id=901,
    home_franchise="Eagles",
    away_franchise="Hawks",
    tier="Premier",
    day=1,
    match_type=MatchType.REGULAR,
    game_name="Lobby1",
    game_pass="pass123",
    var_date=None,
):
    m = MagicMock()
    m.home_team = MagicMock()
    m.home_team.name = home_team_name
    m.home_team.franchise = home_franchise
    m.home_team.tier = tier
    m.home_team.players = home_players
    m.home_team.gm = MagicMock()
    m.home_team.gm.discord_id = home_gm_id
    m.home_team.gm.rsc_name = "HomeGM"

    m.away_team = MagicMock()
    m.away_team.name = away_team_name
    m.away_team.franchise = away_franchise
    m.away_team.tier = tier
    m.away_team.players = away_players
    m.away_team.gm = MagicMock()
    m.away_team.gm.discord_id = away_gm_id
    m.away_team.gm.rsc_name = "AwayGM"

    m.day = day
    m.match_type = match_type
    m.game_name = game_name
    m.game_pass = game_pass
    m.var_date = var_date or datetime(2025, 3, 15, tzinfo=timezone.utc)
    m.id = 1
    return m


# --- discord_member_in_match ---


class TestDiscordMemberInMatch:
    async def test_home_player_found(self, mock_member):
        hp = _make_match_player(discord_id=mock_member.id)
        other = _make_match_player(discord_id=999)
        match = _make_match(home_players=[hp], away_players=[other])
        mixin = _create_mixin()

        assert await mixin.discord_member_in_match(mock_member, match) is True

    async def test_away_player_found(self, mock_member):
        other = _make_match_player(discord_id=999)
        ap = _make_match_player(discord_id=mock_member.id)
        match = _make_match(home_players=[other], away_players=[ap])
        mixin = _create_mixin()

        assert await mixin.discord_member_in_match(mock_member, match) is True

    async def test_not_found(self, mock_member):
        hp = _make_match_player(discord_id=999999)
        other = _make_match_player(discord_id=888)
        match = _make_match(home_players=[hp], away_players=[other])
        mixin = _create_mixin()

        assert await mixin.discord_member_in_match(mock_member, match) is False

    async def test_no_players(self, mock_member):
        match = _make_match(home_players=None, away_players=None)
        mixin = _create_mixin()

        assert await mixin.discord_member_in_match(mock_member, match) is False


# --- get_match_from_list ---


class TestGetMatchFromList:
    async def test_finds_match(self):
        m1 = _make_match(home_team_name="Alpha", away_team_name="Bravo")
        m2 = _make_match(home_team_name="Charlie", away_team_name="Delta")

        result = await MatchMixIn.get_match_from_list("Alpha", "Bravo", [m1, m2])
        assert result is m1

    async def test_returns_none_when_not_found(self):
        m1 = _make_match(home_team_name="Alpha", away_team_name="Bravo")

        result = await MatchMixIn.get_match_from_list("X", "Y", [m1])
        assert result is None

    async def test_case_insensitive(self):
        m1 = _make_match(home_team_name="Alpha", away_team_name="Bravo")

        result = await MatchMixIn.get_match_from_list("alpha", "bravo", [m1])
        assert result is m1

    async def test_skips_matches_with_no_names(self):
        m = _make_match()
        m.home_team.name = None
        result = await MatchMixIn.get_match_from_list("Alpha", "Bravo", [m])
        assert result is None


# --- is_match_franchise_gm ---


class TestIsMatchFranchiseGm:
    async def test_home_gm(self, mock_member):
        match = _make_match(home_gm_id=mock_member.id, away_gm_id=999)
        mixin = _create_mixin()

        assert await mixin.is_match_franchise_gm(mock_member, match) is True

    async def test_away_gm(self, mock_member):
        match = _make_match(home_gm_id=999, away_gm_id=mock_member.id)
        mixin = _create_mixin()

        assert await mixin.is_match_franchise_gm(mock_member, match) is True

    async def test_not_gm(self, mock_member):
        match = _make_match(home_gm_id=999, away_gm_id=888)
        mixin = _create_mixin()

        assert await mixin.is_match_franchise_gm(mock_member, match) is False

    async def test_raises_when_gm_missing(self, mock_member):
        match = _make_match()
        match.home_team.gm = None
        mixin = _create_mixin()

        with pytest.raises(AttributeError, match="missing GM"):
            await mixin.is_match_franchise_gm(mock_member, match)


# --- is_match_franchise_agm ---


def _agm_of(name):
    """A `FranchiseList` as `agm_franchise_of` returns it.

    `name` cannot go through the MagicMock constructor -- it configures the mock
    rather than setting the attribute.
    """
    f = MagicMock()
    f.name = name
    return f


class TestIsMatchFranchiseAgm:
    """AGM membership comes from the API, never from discord role names.

    The old check required a role literally named "Assistant GM" and then
    substring matched the franchise name against every role the member held.
    """

    async def test_not_an_agm(self, mock_member, mock_guild):
        match = _make_match(home_franchise="Eagles", away_franchise="Hawks")
        mixin = _create_mixin(agm_franchise_of=AsyncMock(return_value=None))

        assert await mixin.is_match_franchise_agm(mock_member, match) is False

    async def test_agm_of_home_franchise(self, mock_member, mock_guild):
        match = _make_match(home_franchise="Eagles", away_franchise="Hawks")
        mixin = _create_mixin(agm_franchise_of=AsyncMock(return_value=_agm_of("Eagles")))

        assert await mixin.is_match_franchise_agm(mock_member, match) is True
        assert await mixin.match_franchise_agm_team(mock_member, match) is MatchTeamEnum.HOME

    async def test_agm_of_away_franchise(self, mock_member, mock_guild):
        match = _make_match(home_franchise="Eagles", away_franchise="Hawks")
        mixin = _create_mixin(agm_franchise_of=AsyncMock(return_value=_agm_of("Hawks")))

        assert await mixin.is_match_franchise_agm(mock_member, match) is True
        assert await mixin.match_franchise_agm_team(mock_member, match) is MatchTeamEnum.AWAY

    async def test_agm_of_uninvolved_franchise(self, mock_member, mock_guild):
        match = _make_match(home_franchise="Eagles", away_franchise="Hawks")
        mixin = _create_mixin(agm_franchise_of=AsyncMock(return_value=_agm_of("Sharks")))

        assert await mixin.is_match_franchise_agm(mock_member, match) is False

    async def test_case_insensitive(self, mock_member, mock_guild):
        match = _make_match(home_franchise="Eagles", away_franchise="Hawks")
        mixin = _create_mixin(agm_franchise_of=AsyncMock(return_value=_agm_of("eAgLeS")))

        assert await mixin.is_match_franchise_agm(mock_member, match) is True

    async def test_substring_franchise_does_not_match(self, mock_member, mock_guild):
        """Regression: names are compared for equality, not containment.

        The previous implementation scanned role names with `in`, so an AGM of
        "Eagles Nest" passed for any match involving "Eagles".
        """
        match = _make_match(home_franchise="Eagles", away_franchise="Hawks")
        mixin = _create_mixin(agm_franchise_of=AsyncMock(return_value=_agm_of("Eagles Nest")))

        assert await mixin.is_match_franchise_agm(mock_member, match) is False

    async def test_prefetched_franchise_skips_the_lookup(self, mock_member, mock_guild):
        """`/match` resolves the AGM once and reuses it across both checks."""
        match = _make_match(home_franchise="Eagles", away_franchise="Hawks")
        lookup = AsyncMock(return_value=None)
        mixin = _create_mixin(agm_franchise_of=lookup)

        result = await mixin.is_match_franchise_agm(mock_member, match, agm_franchise=_agm_of("Eagles"))

        assert result is True
        lookup.assert_not_awaited()


# --- is_future_match_date ---


class TestIsFutureMatchDate:
    async def test_future_date(self, mock_guild):
        match = _make_match(var_date=datetime(2099, 12, 31, tzinfo=timezone.utc))
        mixin = _create_mixin()
        mixin.timezone = AsyncMock(return_value=timezone.utc)

        assert await mixin.is_future_match_date(mock_guild, match) is True

    async def test_past_date(self, mock_guild):
        match = _make_match(var_date=datetime(2000, 1, 1, tzinfo=timezone.utc))
        mixin = _create_mixin()
        mixin.timezone = AsyncMock(return_value=timezone.utc)

        assert await mixin.is_future_match_date(mock_guild, match) is False

    async def test_raises_when_no_date(self, mock_guild):
        match = _make_match()
        match.var_date = None
        mixin = _create_mixin()
        mixin.timezone = AsyncMock(return_value=timezone.utc)

        with pytest.raises(AttributeError, match="no date"):
            await mixin.is_future_match_date(mock_guild, match)


# --- match_team_by_user ---


class TestMatchTeamByUser:
    async def test_home_gm(self, mock_member):
        match = _make_match(home_gm_id=mock_member.id, away_gm_id=999, home_players=[], away_players=[])
        mixin = _create_mixin()

        result = await mixin.match_team_by_user(match, mock_member)
        assert result == MatchTeamEnum.HOME

    async def test_away_gm(self, mock_member):
        match = _make_match(home_gm_id=999, away_gm_id=mock_member.id, home_players=[], away_players=[])
        mixin = _create_mixin()

        result = await mixin.match_team_by_user(match, mock_member)
        assert result == MatchTeamEnum.AWAY

    async def test_home_player(self, mock_member):
        hp = _make_match_player(discord_id=mock_member.id)
        match = _make_match(home_gm_id=999, away_gm_id=888, home_players=[hp], away_players=[])
        mixin = _create_mixin()

        result = await mixin.match_team_by_user(match, mock_member)
        assert result == MatchTeamEnum.HOME

    async def test_away_player(self, mock_member):
        ap = _make_match_player(discord_id=mock_member.id)
        match = _make_match(home_gm_id=999, away_gm_id=888, home_players=[], away_players=[ap])
        mixin = _create_mixin()

        result = await mixin.match_team_by_user(match, mock_member)
        assert result == MatchTeamEnum.AWAY

    async def test_home_agm(self, mock_member):
        match = _make_match(
            home_gm_id=999, away_gm_id=888, home_players=[], away_players=[], home_franchise="Eagles", away_franchise="Hawks"
        )
        mixin = _create_mixin(agm_franchise_of=AsyncMock(return_value=_agm_of("Eagles")))
        type(mock_member).guild_permissions = PropertyMock(return_value=discord.Permissions())

        assert await mixin.match_team_by_user(match, mock_member) == MatchTeamEnum.HOME

    async def test_away_agm(self, mock_member):
        match = _make_match(
            home_gm_id=999, away_gm_id=888, home_players=[], away_players=[], home_franchise="Eagles", away_franchise="Hawks"
        )
        mixin = _create_mixin(agm_franchise_of=AsyncMock(return_value=_agm_of("Hawks")))
        type(mock_member).guild_permissions = PropertyMock(return_value=discord.Permissions())

        assert await mixin.match_team_by_user(match, mock_member) == MatchTeamEnum.AWAY

    async def test_admin_gets_home(self, mock_member):
        match = _make_match(home_gm_id=999, away_gm_id=888, home_players=[], away_players=[])
        mixin = _create_mixin(agm_franchise_of=AsyncMock(return_value=None))
        # Give manage_guild permission
        perms = discord.Permissions(manage_guild=True)
        type(mock_member).guild_permissions = PropertyMock(return_value=perms)

        result = await mixin.match_team_by_user(match, mock_member)
        assert result == MatchTeamEnum.HOME

    async def test_admin_who_is_the_away_agm_gets_away(self, mock_member):
        """The AGM check runs ahead of the admin fallback, so an admin who
        actually staffs the away franchise is not flattened to HOME."""
        match = _make_match(
            home_gm_id=999, away_gm_id=888, home_players=[], away_players=[], home_franchise="Eagles", away_franchise="Hawks"
        )
        mixin = _create_mixin(agm_franchise_of=AsyncMock(return_value=_agm_of("Hawks")))
        type(mock_member).guild_permissions = PropertyMock(return_value=discord.Permissions(manage_guild=True))

        assert await mixin.match_team_by_user(match, mock_member) == MatchTeamEnum.AWAY

    async def test_raises_when_not_in_match(self, mock_member):
        match = _make_match(home_gm_id=999, away_gm_id=888, home_players=[], away_players=[])
        mixin = _create_mixin(agm_franchise_of=AsyncMock(return_value=None))
        perms = discord.Permissions()
        type(mock_member).guild_permissions = PropertyMock(return_value=perms)

        with pytest.raises(ValueError, match="not a valid player"):
            await mixin.match_team_by_user(match, mock_member)


# --- API wrappers ---


class TestMatchesApi:
    async def test_returns_matches(self, mock_guild):
        match_resp = MagicMock()
        match_resp.results = [MagicMock()]
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.matches_list.return_value = match_resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.matches.matches.MatchesApi", return_value=mock_api):
                result = await mixin.matches(mock_guild)

        assert len(result) == 1

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.matches_list.side_effect = ApiException(status=500, reason="Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.matches.matches.MatchesApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.matches(mock_guild)


class TestMatchByDayApi:
    async def test_returns_match(self, mock_guild):
        match = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_match_retrieve.return_value = match
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.matches.matches.TeamsApi", return_value=mock_api):
                result = await mixin.match_by_day(mock_guild, team_id=1, day=3)

        assert result is match

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.teams_match_retrieve.side_effect = ApiException(status=404, reason="Not Found")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.matches.matches.TeamsApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.match_by_day(mock_guild, team_id=1, day=3)


class TestFindMatchApi:
    async def test_returns_matches(self, mock_guild):
        resp = MagicMock()
        resp.results = [MagicMock(), MagicMock()]
        mixin = _create_mixin(
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.matches_find_match_retrieve.return_value = resp
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.matches.matches.MatchesApi", return_value=mock_api):
                result = await mixin.find_match(mock_guild, teams=["Alpha", "Bravo"])

        assert len(result) == 2


class TestMatchByIdApi:
    async def test_returns_match(self, mock_guild):
        match = MagicMock()
        match.id = 42
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.matches_retrieve.return_value = match
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.matches.matches.MatchesApi", return_value=mock_api):
                result = await mixin.match_by_id(mock_guild, id=42)

        assert result.id == 42


class TestReportMatchApi:
    async def test_reports_match(self, mock_guild, mock_executor):
        result_mock = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.matches_score_report_create.return_value = result_mock
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.matches.matches.MatchesApi", return_value=mock_api):
                result = await mixin.report_match(
                    mock_guild,
                    match_id=1,
                    ballchasing_group="abc123",
                    home_score=3,
                    away_score=1,
                    executor=mock_executor,
                )

        assert result is result_mock

    async def test_raises_rsc_exception_on_api_error(self, mock_guild, mock_executor):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.matches_score_report_create.side_effect = ApiException(status=400, reason="Bad")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.matches.matches.MatchesApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.report_match(
                        mock_guild,
                        match_id=1,
                        ballchasing_group="abc123",
                        home_score=3,
                        away_score=1,
                        executor=mock_executor,
                    )


class TestCreateMatchApi:
    async def test_creates_match(self, mock_guild):
        created = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.matches_create.return_value = created
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.matches.matches.MatchesApi", return_value=mock_api):
                result = await mixin.create_match(
                    mock_guild,
                    match_type=MatchType.REGULAR,
                    match_format=MatchFormat.BEST_OF_FIVE,
                    home_team_id=1,
                    away_team_id=2,
                    day=1,
                )

        assert result is created


class TestMatchResultsApi:
    async def test_returns_results(self, mock_guild):
        results = MagicMock()
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.matches_results_retrieve.return_value = results
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.matches.matches.MatchesApi", return_value=mock_api):
                result = await mixin.match_results(mock_guild, id=1)

        assert result is results

    async def test_raises_rsc_exception_on_api_error(self, mock_guild):
        mixin = _create_mixin(_api_conf={mock_guild.id: MagicMock()})

        with patch("rsc.abc.ApiClient") as mock_client:
            mock_api = AsyncMock()
            mock_api.matches_results_retrieve.side_effect = ApiException(status=500, reason="Error")
            mock_client.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_client.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("rsc.matches.matches.MatchesApi", return_value=mock_api):
                with pytest.raises(RscException):
                    await mixin.match_results(mock_guild, id=1)
