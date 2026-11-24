"""Tests for writing a member's nickname.

Discord caps a nickname at 32 characters, but nothing caps the RSC name in the
API -- admins park annotations in it ("cosmo6430 - INACTIVE USER - TRANSFER").
Adding a franchise prefix and accolades to one of those overruns the cap, which
is a data problem rather than a bug, so it has to be reportable on its own.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from rsc import const
from rsc.enums import Status
from rsc.exceptions import DiscordNameTooLong
from rsc.transactions.roles import update_league_player_discord
from rsc.types import Accolades
from rsc.utils.utils import NICKNAME_MAX_LENGTH, update_discord_name

from .sync_fakes import OCEAN_ROLE, TIERS, agm_franchise, league_player, role_names, sync_guild, sync_member


@pytest.fixture
def member():
    m = MagicMock(spec=discord.Member)
    m.id = 1114676843518382120
    m.display_name = "cosmo6430"
    m.mention = f"<@{m.id}>"
    m.guild = MagicMock(spec=discord.Guild)
    m.edit = AsyncMock()
    return m


@pytest.fixture(autouse=True)
def no_accolades():
    with patch("rsc.utils.utils.member_accolades", AsyncMock(return_value=Accolades())):
        yield


async def test_prefix_and_name_are_written_when_they_fit(member):
    await update_discord_name(member, name="cosmo6430", prefix="COS")

    member.edit.assert_awaited_once_with(nick="COS | cosmo6430")


async def test_too_long_name_raises_without_touching_the_member(member):
    """The existing nickname is left alone rather than truncated to fit. Half an
    RSC name is not an improvement over a stale prefix, and discord would reject
    the edit anyway."""
    name = "cosmo6430 - INACTIVE USER - TRANSFER"

    with pytest.raises(DiscordNameTooLong) as exc:
        await update_discord_name(member, name=name, prefix="COS")

    member.edit.assert_not_awaited()
    assert exc.value.member_id == member.id
    assert exc.value.nickname == f"COS | {name}"
    assert len(exc.value.nickname) > NICKNAME_MAX_LENGTH


async def test_too_long_name_is_still_a_value_error(member):
    """Every sync path already funnels `ValueError` into a report to whoever ran
    it. Narrowing the type must not drop this out of those handlers."""
    with pytest.raises(ValueError):
        await update_discord_name(member, name="a" * 40)


async def test_accolades_count_against_the_limit(member):
    """The emoji are appended after the name, so a name that fits on its own can
    still overrun once the player has earned enough of them."""
    with (
        patch("rsc.utils.utils.member_accolades", AsyncMock(return_value=Accolades(trophy=10, star=10))),
        pytest.raises(DiscordNameTooLong),
    ):
        await update_discord_name(member, name="cosmo6430", prefix="COS")


async def test_agm_tag_that_does_not_fit_is_reported_after_the_roles_are_written():
    name = "a" * (NICKNAME_MAX_LENGTH - len("FA | "))
    synced = sync_member(sync_guild(), nick=f"FA | {name}")

    with pytest.raises(DiscordNameTooLong):
        await update_league_player_discord(
            guild=synced.guild,
            player=synced,
            league_player=league_player(Status.FREE_AGENT, name=name),
            tiers=TIERS,
            agm_franchise=agm_franchise(),
        )

    assert synced.display_name == f"FA | {name}"
    assert {const.AGM_ROLE, OCEAN_ROLE} <= role_names(synced)
