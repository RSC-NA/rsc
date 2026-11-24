"""Discord role/nickname sync helpers in `rsc.transactions.roles`.

The focus here is the AGM reconcile. A non-playing AGM has no `LeaguePlayer`,
so `update_nonplaying_discord` is the only thing in the codebase that ever sees
them, and it is the API's `Franchise.agms` -- not the discord "Assistant GM"
role -- that has to drive it.
"""

from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from rscapi.models.franchise_gm import FranchiseGM
from rscapi.models.player_transaction_updates import PlayerTransactionUpdates
from rscapi.models.team_player import TeamPlayer
from rscapi.models.transaction_franchise import TransactionFranchise
from rscapi.models.transaction_response import TransactionResponse
from rscapi.models.transaction_team import TransactionTeam

from rsc import const
from rsc.enums import Status
from rsc.transactions import roles

from .sync_fakes import MEMBER_ID, OCEAN_ROLE, TIERS, discord_requests, league_player, role_names, sync_guild, sync_member, sync_role

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
    return sync_role(name, position=1)


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
    return r


@pytest.fixture
def member(mock_guild):
    mock_guild.owner_id = 1
    mock_guild.default_role = sync_role("@everyone", position=0)
    mock_guild.me = MagicMock(spec=discord.Member)
    mock_guild.me.top_role = sync_role("RSC", position=2)
    return sync_member(mock_guild)


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


class TestNonPlayingAgmReconcile:
    async def test_restores_everything_an_agm_lost(self, mock_guild, member, guild_roles):
        """The whole point of the change: an AGM stripped bare in discord is
        rebuilt from the API. The old code read AGM-ness off the discord role,
        so once that was gone nothing could bring any of it back."""
        member.roles = []

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise())

        assert set(member.roles) == {guild_roles.agm, guild_roles.league, guild_roles.franchise}
        assert member.display_name == "OCE | nickm"
        assert discord_requests(member) == 1

    async def test_keeps_state_an_agm_already_has(self, mock_guild, member, guild_roles):
        member.roles = [guild_roles.agm, guild_roles.league, guild_roles.franchise]

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise())

        assert set(member.roles) == {guild_roles.agm, guild_roles.league, guild_roles.franchise}

    async def test_strips_a_stale_franchise_role(self, mock_guild, member, guild_roles, monkeypatch):
        """An AGM keeps exactly the one franchise the API gives them."""
        member.roles = [guild_roles.agm, guild_roles.other_franchise]
        monkeypatch.setattr(roles.utils, "franchise_role_list_from_disord_member", AsyncMock(return_value=[guild_roles.other_franchise]))

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise())

        assert guild_roles.other_franchise not in member.roles
        assert guild_roles.franchise in member.roles

    async def test_no_former_player_role_for_an_agm(self, mock_guild, member, guild_roles):
        """A franchise prefix on an AGM means "staff", not "used to play"."""
        member.display_name = "OCE | nickm"
        member.roles = []

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise())

        assert guild_roles.former_player not in member.roles

    async def test_falls_back_to_name_lookup_when_franchise_has_no_gm(self, mock_guild, member, guild_roles):
        """Franchise roles embed the GM name, so a franchise between GMs has no
        role name to build. The AGM still gets their roles and prefix."""
        roles.utils.franchise_role_from_model = AsyncMock(side_effect=AttributeError("no GM"))

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise(gm=None))

        role_from_name = roles.utils.franchise_role_from_name
        assert isinstance(role_from_name, AsyncMock)
        role_from_name.assert_awaited_once()
        assert guild_roles.franchise in member.roles
        assert guild_roles.agm in member.roles
        assert member.display_name == "OCE | nickm"

    async def test_missing_franchise_role_leaves_existing_ones_alone(self, mock_guild, member, guild_roles, monkeypatch):
        """Do not strip what cannot be replaced."""
        member.roles = [guild_roles.other_franchise]
        roles.utils.franchise_role_from_model = AsyncMock(side_effect=ValueError("no such role"))
        roles.utils.franchise_role_from_name = AsyncMock(return_value=None)
        monkeypatch.setattr(roles.utils, "franchise_role_list_from_disord_member", AsyncMock(return_value=[guild_roles.other_franchise]))

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise())

        assert guild_roles.other_franchise in member.roles

    async def test_long_nickname_does_not_abort_the_sync(self, mock_guild, member, guild_roles):
        """`/transactions retire` does not wrap this call, so raising here would
        report the retire as failed after the API mutation already landed."""
        too_long = _franchise(rsc_name="a name far too long for discord to take")

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=too_long)

        assert set(member.roles) == {guild_roles.agm, guild_roles.league, guild_roles.franchise}
        assert member.display_name == "nickm"

    async def test_falls_back_to_display_name_when_api_has_no_rsc_name(self, mock_guild, member, guild_roles):
        member.display_name = "FA | nickm"

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=_franchise(rsc_name=None))

        assert member.display_name == "OCE | nickm"


class TestNonPlayingNonAgm:
    async def test_strips_agm_state_when_the_api_has_no_record(self, mock_guild, member, guild_roles, monkeypatch):
        """The other direction of the same reconcile. Before this, a removed AGM
        kept the role, the franchise role and the prefix indefinitely."""
        member.display_name = "OCE | nickm"
        member.roles = [guild_roles.agm, guild_roles.league, guild_roles.franchise]
        monkeypatch.setattr(roles.utils, "franchise_role_list_from_disord_member", AsyncMock(return_value=[guild_roles.franchise]))

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=None)

        assert member.roles == [guild_roles.former_player]
        assert member.display_name == "nickm"
        assert discord_requests(member) == 1

    async def test_former_player_still_inferred_from_a_prefix(self, mock_guild, member, guild_roles, monkeypatch):
        member.display_name = "OCE | nickm"
        member.roles = []
        monkeypatch.setattr(roles.utils, "franchise_role_list_from_disord_member", AsyncMock(return_value=[]))

        await roles.update_nonplaying_discord(guild=mock_guild, member=member, tiers=[], agm_franchise=None)

        assert guild_roles.former_player in member.roles

    async def test_a_nickname_that_is_only_a_prefix_gets_the_roles_then_the_error(self):
        member = sync_member(sync_guild(), held=[const.LEAGUE_ROLE], nick="FA | ")

        with pytest.raises(ValueError, match="Empty"):
            await roles.update_nonplaying_discord(guild=member.guild, member=member, tiers=TIERS, agm_franchise=None)

        assert role_names(member) == {const.FORMER_PLAYER_ROLE}
        assert member.display_name == "FA | "
        assert discord_requests(member) == 1


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

        assert guild_roles.agm in member.roles

    async def test_removes_a_stale_agm_role(self, mock_guild, member, guild_roles):
        member.roles = [guild_roles.agm]

        await roles.update_rostered_discord(
            guild=mock_guild, player=member, league_player=self._league_player(), tiers=[], agm_franchise=None
        )

        assert guild_roles.agm not in member.roles

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

        assert guild_roles.ir in member.roles

    async def test_ir_role_removed_when_rostered(self, mock_guild, member, guild_roles):
        member.roles = [guild_roles.ir]

        await roles.update_rostered_discord(
            guild=mock_guild,
            player=member,
            league_player=self._league_player(status=Status.ROSTERED),
            tiers=[],
            agm_franchise=None,
        )

        assert guild_roles.ir not in member.roles


class TestDraftEligible:
    async def test_drops_permfa_in_waiting(self):
        member = sync_member(sync_guild(), held=[const.LEAGUE_ROLE, const.PERM_FA_WAITING_ROLE], nick="PFW | nickm")

        await roles.update_league_player_discord(
            guild=member.guild, player=member, league_player=league_player(Status.DRAFT_ELIGIBLE), tiers=TIERS, agm_franchise=None
        )

        held = role_names(member)
        assert const.PERM_FA_WAITING_ROLE not in held
        assert const.DRAFT_ELIGIBLE in held


class TestDispatcher:
    async def test_forwards_agm_franchise_when_there_is_no_league_player(self, mock_guild, member, monkeypatch):
        sync = AsyncMock()
        monkeypatch.setattr(roles, "update_nonplaying_discord", sync)
        f = _franchise()

        await roles.update_league_player_discord(guild=mock_guild, player=member, agm_franchise=f)

        assert sync.await_args is not None
        assert sync.await_args.kwargs["agm_franchise"] is f

    @pytest.mark.parametrize("status", [Status.DROPPED, Status.FORMER, Status.BANNED])
    async def test_forwards_agm_franchise_for_non_playing_statuses(self, mock_guild, member, monkeypatch, status):
        sync = AsyncMock()
        monkeypatch.setattr(roles, "update_nonplaying_discord", sync)
        lp = MagicMock()
        lp.status = status
        f = _franchise()

        await roles.update_league_player_discord(guild=mock_guild, player=member, league_player=lp, agm_franchise=f)

        assert sync.await_args is not None
        assert sync.await_args.kwargs["agm_franchise"] is f


def _transaction(status: Status, old_tier: str | None = None, new_tier: str | None = None) -> PlayerTransactionUpdates:
    return PlayerTransactionUpdates.model_construct(
        player=league_player(status),
        old_team=TransactionTeam.model_construct(name="Waves", tier=old_tier) if old_tier else None,
        new_team=TransactionTeam.model_construct(name="Waves", tier=new_tier) if new_tier else None,
    )


def _cut_from_the_ocean(gm_id: int) -> TransactionResponse:
    franchise = TransactionFranchise.model_construct(name="The Ocean", prefix="OCE", gm=FranchiseGM(rsc_name="someone", discord_id=gm_id))
    return TransactionResponse.model_construct(first_franchise=franchise)


class TestTransactionWrites:
    async def test_a_signed_free_agent_swaps_roles_and_takes_the_franchise_tag_in_one_request(self):
        guild = sync_guild()
        member = sync_member(guild, held=[const.LEAGUE_ROLE, const.FREE_AGENT_ROLE, "Premier", "PremierFA"], nick="FA | nickm")

        await roles.update_signed_player_discord(
            guild=guild, player=member, ptu=_transaction(Status.ROSTERED, new_tier="Premier"), tiers=TIERS
        )

        assert role_names(member) == {const.LEAGUE_ROLE, "Premier", OCEAN_ROLE}
        assert member.display_name == "OCE | nickm"
        assert discord_requests(member) == 1

    async def test_a_cut_player_swaps_roles_and_takes_the_free_agent_tag_in_one_request(self):
        guild = sync_guild()
        member = sync_member(guild, held=[const.LEAGUE_ROLE, const.CAPTAIN_ROLE, "Premier", OCEAN_ROLE], nick="OCE | nickm")

        await roles.update_cut_player_discord(
            guild=guild, player=member, response=_cut_from_the_ocean(gm_id=7), ptu=_transaction(Status.FREE_AGENT, old_tier="Premier")
        )

        assert role_names(member) == {const.LEAGUE_ROLE, "Premier", const.FREE_AGENT_ROLE, "PremierFA"}
        assert member.display_name == "FA | nickm"
        assert discord_requests(member) == 1

    async def test_a_cut_gm_keeps_the_franchise_role_and_tag_and_loses_the_captain_role_in_one_request(self):
        guild = sync_guild()
        member = sync_member(guild, held=[const.LEAGUE_ROLE, const.CAPTAIN_ROLE, "Premier", OCEAN_ROLE], nick="OCE | nickm")

        await roles.update_cut_player_discord(
            guild=guild,
            player=member,
            response=_cut_from_the_ocean(gm_id=MEMBER_ID),
            ptu=_transaction(Status.FREE_AGENT, old_tier="Premier"),
        )

        assert role_names(member) == {const.LEAGUE_ROLE, "Premier", OCEAN_ROLE}
        assert member.display_name == "OCE | nickm"
        assert discord_requests(member) == 1

    async def test_a_cut_repeated_on_the_member_it_produced_sends_nothing(self):
        guild = sync_guild()
        member = sync_member(guild, held=[const.LEAGUE_ROLE, "Premier", const.FREE_AGENT_ROLE, "PremierFA"], nick="FA | nickm")

        await roles.update_cut_player_discord(
            guild=guild, player=member, response=_cut_from_the_ocean(gm_id=7), ptu=_transaction(Status.FREE_AGENT, old_tier="Premier")
        )

        assert discord_requests(member) == 0

    async def test_a_captain_change_moves_the_role_and_touches_nobody_else(self):
        guild = sync_guild()
        new_captain = sync_member(guild, held=[const.LEAGUE_ROLE])
        old_captain = sync_member(guild, held=[const.LEAGUE_ROLE, const.CAPTAIN_ROLE])
        teammate = sync_member(guild, held=[const.LEAGUE_ROLE])
        members = {1: new_captain, 2: old_captain, 3: teammate}
        guild.get_member = MagicMock(side_effect=members.get)

        await roles.update_team_captain_discord(
            guild=guild,
            players=[
                TeamPlayer.model_construct(name="new", discord_id=1, captain=True),
                TeamPlayer.model_construct(name="old", discord_id=2, captain=False),
                TeamPlayer.model_construct(name="mate", discord_id=3, captain=False),
            ],
        )

        assert role_names(new_captain) == {const.LEAGUE_ROLE, const.CAPTAIN_ROLE}
        assert role_names(old_captain) == {const.LEAGUE_ROLE}
        assert role_names(teammate) == {const.LEAGUE_ROLE}
        assert [discord_requests(member) for member in (new_captain, old_captain, teammate)] == [1, 1, 0]
        assert [member.display_name for member in (new_captain, old_captain, teammate)] == ["nickm", "nickm", "nickm"]


class TestCaptainUpdate:
    @pytest.mark.parametrize(
        ("captain", "held", "requests"),
        [
            pytest.param(True, True, 0, id="a captain who holds the role keeps it"),
            pytest.param(True, False, 1, id="a captain without the role gains it"),
            pytest.param(False, True, 1, id="a non-captain who holds the role loses it"),
            pytest.param(False, False, 0, id="a non-captain without the role is untouched"),
        ],
    )
    async def test_a_member_holds_the_captain_role_only_while_captain(self, captain: bool, held: bool, requests: int):
        guild = sync_guild()
        member = sync_member(guild, held=[const.LEAGUE_ROLE, const.CAPTAIN_ROLE] if held else [const.LEAGUE_ROLE])
        guild.get_member = MagicMock(return_value=member)

        await roles.update_team_captain_discord(
            guild=guild, players=[TeamPlayer.model_construct(name="nickm", discord_id=MEMBER_ID, captain=captain)]
        )

        assert role_names(member) == ({const.LEAGUE_ROLE, const.CAPTAIN_ROLE} if captain else {const.LEAGUE_ROLE})
        assert discord_requests(member) == requests


class TestCutPlayer:
    @pytest.mark.parametrize(
        "fa_roles_held",
        [
            pytest.param([const.FREE_AGENT_ROLE, "PremierFA"], id="holds both FA roles"),
            pytest.param([const.FREE_AGENT_ROLE], id="holds only Free Agent"),
            pytest.param(["PremierFA"], id="holds only the tier FA role"),
            pytest.param([], id="holds neither FA role"),
        ],
    )
    async def test_a_cut_gm_keeps_the_franchise_and_holds_no_free_agent_role(self, fa_roles_held: list[str]):
        guild = sync_guild()
        member = sync_member(guild, held=[const.LEAGUE_ROLE, const.CAPTAIN_ROLE, "Premier", OCEAN_ROLE, *fa_roles_held], nick="OCE | nickm")

        await roles.update_cut_player_discord(
            guild=guild,
            player=member,
            response=_cut_from_the_ocean(gm_id=MEMBER_ID),
            ptu=_transaction(Status.FREE_AGENT, old_tier="Premier"),
        )

        assert role_names(member) == {const.LEAGUE_ROLE, "Premier", OCEAN_ROLE}
        assert member.display_name == "OCE | nickm"

    async def test_a_cut_player_who_is_not_the_gm_becomes_a_free_agent(self):
        guild = sync_guild()
        member = sync_member(guild, held=[const.LEAGUE_ROLE, const.CAPTAIN_ROLE, "Premier", OCEAN_ROLE], nick="OCE | nickm")

        await roles.update_cut_player_discord(
            guild=guild, player=member, response=_cut_from_the_ocean(gm_id=7), ptu=_transaction(Status.FREE_AGENT, old_tier="Premier")
        )

        assert role_names(member) == {const.LEAGUE_ROLE, "Premier", const.FREE_AGENT_ROLE, "PremierFA"}
        assert member.display_name == "FA | nickm"
