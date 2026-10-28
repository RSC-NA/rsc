"""Phase 1 of the Discord UI refresh (docs/discord-ui-refresh.md).

Covers the persistent `/playerinfo` buttons, the Report Match modal's
rejected-submission flag, and confirm/decline handlers acknowledging the click.
"""

import re
from unittest.mock import AsyncMock, MagicMock, create_autospec

import discord
import pytest
from redbot.core.bot import Red

from rsc.admin.views import ConfirmSyncView, CreateFranchiseView, DeleteFranchiseView
from rsc.ballchasing.modals import ReportMatchModal
from rsc.core import RSC
from rsc.enums import BulkRoleAction
from rsc.freeagents.views import CheckInView, CheckOutView
from rsc.members.views.player_info import PLAYER_INFO_TEMPLATE, PlayerInfoButton, PlayerInfoKind, player_info_view
from rsc.utils.views.bulk_role import BulkRoleConfirmView

GUILD_ID = 395806681994493964
TEMPLATE = re.compile(PLAYER_INFO_TEMPLATE)


def _interaction(cog=None, *, configured=True):
    guild = MagicMock(spec=discord.Guild)
    guild.id = GUILD_ID
    guild.name = "RSC 3v3"

    if cog is not None:
        cog._api_conf = {GUILD_ID: MagicMock()} if configured else {}
        cog._league = {GUILD_ID: 1} if configured else {}

    client = MagicMock(spec=Red)
    client.get_cog.return_value = cog

    interaction = MagicMock(spec=discord.Interaction)
    interaction.client = client
    interaction.guild = guild
    interaction.user = MagicMock(spec=discord.Member)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.response.send_message = AsyncMock()
    interaction.response.edit_message = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


class TestPlayerInfoButton:
    @pytest.mark.parametrize("kind", list(PlayerInfoKind))
    def test_custom_id_round_trips(self, kind):
        button = PlayerInfoButton(kind, "Hex Systems: Elite")
        match = TEMPLATE.fullmatch(button.item.custom_id or "")
        assert match is not None
        assert match["kind"] == kind
        assert match["name"] == "Hex Systems: Elite"

    def test_ignores_other_components(self):
        assert TEMPLATE.fullmatch("intent_dm:1:2:yes") is None
        assert TEMPLATE.fullmatch("player_info:trophies:Quantum") is None

    def test_view_never_times_out(self):
        view = player_info_view(team="Quantum", franchise="Hex Systems")
        assert view is not None
        assert view.timeout is None
        assert [c.custom_id for c in view.children] == ["player_info:roster:Quantum", "player_info:franchise:Hex Systems"]

    def test_skips_names_too_long_for_a_custom_id(self):
        long_name = "x" * 90
        view = player_info_view(team="Quantum", franchise=long_name)
        assert view is not None
        assert [c.custom_id for c in view.children] == ["player_info:roster:Quantum"]
        assert player_info_view(team=long_name, franchise=long_name) is None

    async def test_roster_click_replies_ephemerally(self):
        cog = create_autospec(RSC, instance=True)
        cog.players.return_value = []
        cog.build_roster_embed.return_value = discord.Embed(title="Roster")
        interaction = _interaction(cog)

        await PlayerInfoButton(PlayerInfoKind.ROSTER, "Quantum").callback(interaction)

        interaction.response.defer.assert_awaited_once_with(ephemeral=True)
        cog.players.assert_awaited_once_with(interaction.guild, team_name="Quantum", limit=10)
        interaction.followup.send.assert_awaited_once_with(embed=cog.build_roster_embed.return_value, ephemeral=True)

    async def test_franchise_click_replies_ephemerally(self):
        cog = create_autospec(RSC, instance=True)
        cog.teams.return_value = [MagicMock()]
        cog.build_franchise_teams_embed.return_value = discord.Embed(title="Teams")
        interaction = _interaction(cog)

        await PlayerInfoButton(PlayerInfoKind.FRANCHISE, "Hex Systems").callback(interaction)

        cog.teams.assert_awaited_once_with(interaction.guild, franchise="Hex Systems")
        interaction.followup.send.assert_awaited_once_with(embed=cog.build_franchise_teams_embed.return_value, ephemeral=True)

    async def test_click_before_setup_explains_instead_of_crashing(self):
        cog = create_autospec(RSC, instance=True)
        interaction = _interaction(cog, configured=False)

        await PlayerInfoButton(PlayerInfoKind.ROSTER, "Quantum").callback(interaction)

        cog.players.assert_not_awaited()
        assert interaction.followup.send.await_args.kwargs["ephemeral"] is True


    async def test_click_outside_red_is_refused(self):
        interaction = _interaction(create_autospec(RSC, instance=True))
        interaction.client = MagicMock(spec=discord.Client)

        await PlayerInfoButton(PlayerInfoKind.ROSTER, "Quantum").callback(interaction)

        assert interaction.followup.send.await_args.kwargs["ephemeral"] is True


def _report_modal(home: str, away: str) -> tuple[ReportMatchModal, MagicMock]:
    modal = ReportMatchModal(home_team="Quantum", away_team="Voltage")
    modal.home_score.component._value = home  # type: ignore[attr-defined]
    modal.away_score.component._value = away  # type: ignore[attr-defined]
    modal.upload_replays.component._values = [MagicMock(spec=discord.Attachment)]  # type: ignore[attr-defined]
    return modal, _interaction()


class TestReportMatchModal:
    async def test_valid_submission(self):
        modal, interaction = _report_modal("3", "1")
        await modal.on_submit(interaction)
        assert modal.valid
        assert (modal.home_wins, modal.away_wins) == (3, 1)

    async def test_rejected_score_is_not_valid(self):
        """The modal already replied, so the caller must not send a second error."""
        modal, interaction = _report_modal("x", "1")
        await modal.on_submit(interaction)
        assert not modal.valid
        interaction.response.send_message.assert_awaited_once()


def _check_in(interaction):
    return CheckInView(interaction, tier="Elite")


def _check_out(interaction):
    return CheckOutView(interaction, tier="Elite")


def _delete_franchise(interaction):
    return DeleteFranchiseView(interaction, name="Hex Systems")


def _create_franchise(interaction):
    return CreateFranchiseView(interaction, name="Hex Systems", gm=MagicMock(spec=discord.Member))


def _bulk_role(interaction):
    return BulkRoleConfirmView(interaction, BulkRoleAction.ADD, MagicMock(spec=discord.Role), count=3)


class TestClicksAreAcknowledged:
    """Every button press must get an interaction response within 3 seconds.

    These handlers edit the original message through the command's own
    interaction, which does not answer the click.
    """

    @pytest.mark.parametrize("factory", [_check_in, _check_out, _delete_franchise, _create_franchise])
    @pytest.mark.parametrize("handler", ["confirm", "decline"])
    async def test_confirm_and_decline(self, factory, handler):
        view = factory(_interaction())
        click = _interaction()
        await getattr(view, handler)(click)
        click.response.defer.assert_awaited_once()

    @pytest.mark.parametrize("factory", [lambda i: ConfirmSyncView(i), _bulk_role])
    async def test_decline(self, factory):
        view = factory(_interaction())
        click = _interaction()
        await view.decline(click)
        click.response.defer.assert_awaited_once()
