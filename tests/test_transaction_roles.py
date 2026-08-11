"""Discord role/nickname sync helpers in `rsc.transactions.roles`.

The focus here is the AGM reconcile. A non-playing AGM has no `LeaguePlayer`,
so `update_nonplaying_discord` is the only thing in the codebase that ever sees
them, and it is the API's `Franchise.agms` -- not the discord "Assistant GM"
role -- that has to drive it.
"""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rsc import const
from rsc.enums import Status
from rsc.transactions import roles

AGM_ID = 138778232802508801

# Every role getter in `utils` the sync helpers reach for, mapped to the
# attribute the mock is exposed under and the guild role name it carries.
# The names matter: `update_nonplaying_discord` strips player roles by matching
# `role.name` against the constants, so a mock named anything else is invisible
# to that sweep.
ROLE_GETTERS = {
    "get_agm_role": ("agm", const.AGM_ROLE),
    "get_league_role": ("league", const.LEAGUE_ROLE),
    "get_former_player_role": ("former_player", const.FORMER_PLAYER_ROLE),
    "get_spectator_role": ("spectator", const.SPECTATOR_ROLE),
    "get_free_agent_role": ("free_agent", const.FREE_AGENT_ROLE),
    "get_permfa_role": ("permfa", const.PERM_FA_ROLE),
    "get_permfa_waiting_role": ("permfa_waiting", const.PERM_FA_WAITING_ROLE),
    "get_draft_eligible_role": ("draft_eligible", const.DRAFT_ELIGIBLE),
    "get_ir_role": ("ir", const.IR_ROLE),
    "get_captain_role": ("captain", const.CAPTAIN_ROLE),
}


def _role(name):
    """`name` cannot go through the MagicMock constructor -- it configures the
    mock rather than setting the attribute."""
    r = MagicMock(spec=discord.Role)
    r.name = name
    return r


class Roles:
    """Named handles on the mock roles, so tests can assert on identity."""

    def __init__(self):
        for attr, name in ROLE_GETTERS.values():
            setattr(self, attr, _role(name))
        self.franchise = _role("The Ocean (someone)")
        self.other_franchise = _role("The Desert (someoneelse)")


@pytest.fixture
def guild_roles(monkeypatch):
    """Patch the `utils` role lookups the sync helpers use."""
    r = Roles()
    for getter, (attr, _name) in ROLE_GETTERS.items():
        monkeypatch.setattr(roles.utils, getter, AsyncMock(return_value=getattr(r, attr)))

    monkeypatch.setattr(roles.utils, "franchise_role_from_model", AsyncMock(return_value=r.franchise))
    monkeypatch.setattr(roles.utils, "franchise_role_from_name", AsyncMock(return_value=r.franchise))
    monkeypatch.setattr(roles.utils, "update_discord_name", AsyncMock())
    return r


@pytest.fixture
def member():
    m = MagicMock(spec=discord.Member)
    m.id = AGM_ID
    m.display_name = "nickm"
    m.mention = f"<@{AGM_ID}>"
    m.roles = []
    m.add_roles = AsyncMock()
    m.remove_roles = AsyncMock()
    m.edit = AsyncMock()
    return m


def _franchise(name="The Ocean", prefix="OCE", agm_ids=(AGM_ID,), rsc_name="nickm", gm="someone"):
    f = MagicMock()
    f.name = name
    f.prefix = prefix
    f.gm = MagicMock(rsc_name=gm) if gm else None
    f.agms = []
    for i in agm_ids:
        agm = MagicMock()
        agm.discord_id = i
        agm.rsc_name = rsc_name
        f.agms.append(agm)
    return f


def _added(member):
    return set(member.add_roles.await_args.args) if member.add_roles.await_args else set()


def _removed(member):
    return set(member.remove_roles.await_args.args) if member.remove_roles.await_args else set()


class TestNonPlayingAgmReconcile:
    async def test_restores_everything_an_agm_lost(self, mock_guild, member, guild_roles):
        """The whole point of the change: an AGM stripped bare in discord is
        rebuilt from the API. The old code read AGM-ness off the discord role,
        so once that was gone nothing could bring any of it back."""
        member.roles = []

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise())

        added = _added(member)
        assert guild_roles.agm in added
        assert guild_roles.league in added
        assert guild_roles.franchise in added

        roles.utils.update_discord_name.assert_awaited_once()
        kwargs = roles.utils.update_discord_name.await_args.kwargs
        assert kwargs["prefix"] == "OCE"
        assert kwargs["name"] == "nickm"

    async def test_keeps_state_an_agm_already_has(self, mock_guild, member, guild_roles):
        member.roles = [guild_roles.agm, guild_roles.league, guild_roles.franchise]

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise())

        assert guild_roles.franchise not in _removed(member)
        assert guild_roles.agm not in _removed(member)
        assert guild_roles.league not in _removed(member)

    async def test_strips_a_stale_franchise_role(self, mock_guild, member, guild_roles):
        """An AGM keeps exactly the one franchise the API gives them."""
        member.roles = [guild_roles.agm, guild_roles.other_franchise]
        roles.utils.franchise_role_list_from_disord_member = AsyncMock(return_value=[guild_roles.other_franchise])

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise())

        assert guild_roles.other_franchise in _removed(member)
        assert guild_roles.franchise in _added(member)

    async def test_no_former_player_role_for_an_agm(self, mock_guild, member, guild_roles):
        """A franchise prefix on an AGM means "staff", not "used to play"."""
        member.display_name = "OCE | nickm"
        member.roles = []

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise())

        assert guild_roles.former_player not in _added(member)

    async def test_falls_back_to_name_lookup_when_franchise_has_no_gm(self, mock_guild, member, guild_roles):
        """Franchise roles embed the GM name, so a franchise between GMs has no
        role name to build. The AGM still gets their roles and prefix."""
        roles.utils.franchise_role_from_model = AsyncMock(side_effect=AttributeError("no GM"))

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise(gm=None))

        roles.utils.franchise_role_from_name.assert_awaited_once()
        assert guild_roles.franchise in _added(member)
        assert guild_roles.agm in _added(member)

    async def test_missing_franchise_role_leaves_existing_ones_alone(self, mock_guild, member, guild_roles):
        """Do not strip what cannot be replaced."""
        member.roles = [guild_roles.other_franchise]
        roles.utils.franchise_role_from_model = AsyncMock(side_effect=ValueError("no such role"))
        roles.utils.franchise_role_from_name = AsyncMock(return_value=None)
        roles.utils.franchise_role_list_from_disord_member = AsyncMock(return_value=[guild_roles.other_franchise])

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise())

        assert guild_roles.other_franchise not in _removed(member)

    async def test_long_nickname_does_not_abort_the_sync(self, mock_guild, member, guild_roles):
        """`/transactions retire` does not wrap this call, so raising here would
        report the retire as failed after the API mutation already landed."""
        roles.utils.update_discord_name = AsyncMock(side_effect=ValueError("Discord name is too long"))

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise())

        member.add_roles.assert_awaited_once()

    async def test_falls_back_to_display_name_when_api_has_no_rsc_name(self, mock_guild, member, guild_roles):
        member.display_name = "OCE | nickm"

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise(rsc_name=None))

        assert roles.utils.update_discord_name.await_args.kwargs["name"] == "nickm"


class TestNonPlayingNonAgm:
    async def test_strips_agm_state_when_the_api_has_no_record(self, mock_guild, member, guild_roles):
        """The other direction of the same reconcile. Before this, a removed AGM
        kept the role, the franchise role and the prefix indefinitely."""
        member.display_name = "OCE | nickm"
        member.roles = [guild_roles.agm, guild_roles.league, guild_roles.franchise]
        roles.utils.franchise_role_list_from_disord_member = AsyncMock(return_value=[guild_roles.franchise])

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=None)

        removed = _removed(member)
        assert guild_roles.agm in removed
        assert guild_roles.league in removed
        assert guild_roles.franchise in removed
        member.edit.assert_awaited_once_with(nick="nickm")

    async def test_former_player_still_inferred_from_a_prefix(self, mock_guild, member, guild_roles):
        member.display_name = "OCE | nickm"
        member.roles = []
        roles.utils.franchise_role_list_from_disord_member = AsyncMock(return_value=[])

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=None)

        assert guild_roles.former_player in _added(member)


class TestRosteredAgm:
    """A rostered AGM gets their franchise role and prefix from the roster, but
    nothing else reconciles the AGM role itself."""

    def _league_player(self, status=Status.ROSTERED, tier="Premier", franchise="The Ocean"):
        lp = MagicMock()
        lp.status = status
        lp.tier = MagicMock()
        lp.tier.name = tier
        lp.captain = False
        lp.team = MagicMock()
        lp.team.franchise = MagicMock()
        lp.team.franchise.prefix = "OCE"
        lp.team.franchise.name = franchise
        lp.player = MagicMock()
        lp.player.name = "nickm"
        return lp

    @pytest.fixture(autouse=True)
    def _rostered_utils(self, monkeypatch, guild_roles):
        monkeypatch.setattr(roles.utils, "get_tier_role", AsyncMock(return_value=_role("Premier")))
        monkeypatch.setattr(roles.utils, "franchise_role_from_league_player", AsyncMock(return_value=guild_roles.franchise))
        monkeypatch.setattr(roles.utils, "franchise_role_list_from_disord_member", AsyncMock(return_value=[]))

    async def test_adds_the_agm_role(self, mock_guild, member, guild_roles):
        await roles.update_rostered_discord(
            guild=mock_guild,
            player=member,
            league_player=self._league_player(),
            tiers=[],
            agm_franchise=_franchise(),
        )

        assert guild_roles.agm in _added(member)

    async def test_removes_a_stale_agm_role(self, mock_guild, member, guild_roles):
        member.roles = [guild_roles.agm]

        await roles.update_rostered_discord(
            guild=mock_guild, player=member, league_player=self._league_player(), tiers=[], agm_franchise=None
        )

        assert guild_roles.agm in _removed(member)

    @pytest.mark.parametrize("status", [Status.IR, Status.AGMIR])
    async def test_ir_role_is_applied(self, mock_guild, member, guild_roles, status):
        """Regression: this read `player.status` -- a discord.Member's
        online/idle presence -- so it never matched a league Status. The IR role
        was never added and always removed, which hit AGM IR in particular."""
        await roles.update_rostered_discord(
            guild=mock_guild,
            player=member,
            league_player=self._league_player(status=status),
            tiers=[],
            agm_franchise=None,
        )

        assert guild_roles.ir in _added(member)
        assert guild_roles.ir not in _removed(member)

    async def test_ir_role_removed_when_rostered(self, mock_guild, member, guild_roles):
        member.roles = [guild_roles.ir]

        await roles.update_rostered_discord(
            guild=mock_guild,
            player=member,
            league_player=self._league_player(status=Status.ROSTERED),
            tiers=[],
            agm_franchise=None,
        )

        assert guild_roles.ir in _removed(member)


class TestDispatcher:
    async def test_forwards_agm_franchise_when_there_is_no_league_player(self, mock_guild, member, monkeypatch):
        sync = AsyncMock()
        monkeypatch.setattr(roles, "update_nonplaying_discord", sync)
        f = _franchise()

        await roles.update_league_player_discord(guild=mock_guild, player=member, agm_franchise=f)

        assert sync.await_args.kwargs["agm_franchise"] is f

    @pytest.mark.parametrize("status", [Status.DROPPED, Status.FORMER, Status.BANNED])
    async def test_forwards_agm_franchise_for_non_playing_statuses(self, mock_guild, member, monkeypatch, status):
        sync = AsyncMock()
        monkeypatch.setattr(roles, "update_nonplaying_discord", sync)
        lp = MagicMock()
        lp.status = status
        f = _franchise()

        await roles.update_league_player_discord(guild=mock_guild, player=member, league_player=lp, agm_franchise=f)

        assert sync.await_args.kwargs["agm_franchise"] is f

    async def test_conflicting_status_is_logged_and_still_dispatched(self, mock_guild, member, monkeypatch, caplog):
        """An AGM can only sign with the franchise they staff, so an AGM record
        alongside a free agent status means the two API records disagree."""
        sync = AsyncMock()
        monkeypatch.setattr(roles, "update_free_agent_discord", sync)
        lp = MagicMock()
        lp.status = Status.FREE_AGENT

        with caplog.at_level("WARNING"):
            await roles.update_league_player_discord(guild=mock_guild, player=member, league_player=lp, agm_franchise=_franchise())

        sync.assert_awaited_once()
        assert "reconciled by hand" in caplog.text
