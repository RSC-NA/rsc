"""What members and staff see once no season is taking sign-ups."""

from unittest.mock import AsyncMock, MagicMock

import discord

from rsc.admin.intents import AdminIntentsMixIn
from rsc.admin.stats import AdminStatsMixIn
from rsc.members.members import MemberMixIn

from .utils import command_callback

CURRENT_SEASON = MagicMock(id=11, number=27)


def _mixin(cls, **attrs):
    saved = cls.__abstractmethods__
    cls.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(cls)
    finally:
        cls.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _interaction(guild, user) -> MagicMock:
    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = guild
    interaction.user = user
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    return interaction


def _reply(interaction: MagicMock) -> tuple[str | None, str | None]:
    """Title and description of the one embed the command answered with"""
    [call] = interaction.followup.send.await_args_list
    embed = call.kwargs["embed"]
    return embed.title, embed.description


class TestMemberCommands:
    async def test_signup_status_falls_back_to_the_current_season(self, mock_guild, mock_member, no_signup_season_lookup):
        mixin = _mixin(
            MemberMixIn,
            next_signup_season=no_signup_season_lookup,
            current_season=AsyncMock(return_value=CURRENT_SEASON),
            players=AsyncMock(return_value=[]),
        )
        interaction = _interaction(mock_guild, mock_member)

        await mixin._signup_status_flow(interaction)

        assert _reply(interaction) == ("Sign-up Status", "You are currently **not** signed up for the league.")
        assert mixin.players.await_args.kwargs["season"] == CURRENT_SEASON.id

    async def test_signup_says_signups_are_closed(self, mock_guild, mock_member, no_signup_season_lookup):
        mixin = _mixin(MemberMixIn, next_signup_season=no_signup_season_lookup)
        interaction = _interaction(mock_guild, mock_member)

        await command_callback(MemberMixIn._member_signup)(mixin, interaction)

        assert _reply(interaction) == (
            "Signups Closed",
            "Signups are not currently open for RSC. Please try again when the next season is accepting signups.",
        )


class TestAdminCommands:
    async def test_intent_stats_fall_back_to_the_current_season(self, mock_guild, mock_member, no_signup_season_lookup):
        mixin = _mixin(
            AdminStatsMixIn,
            next_signup_season=no_signup_season_lookup,
            current_season=AsyncMock(return_value=CURRENT_SEASON),
            player_intents=AsyncMock(return_value=[]),
        )
        interaction = _interaction(mock_guild, mock_member)

        await command_callback(AdminStatsMixIn._intent_stats_cmd)(mixin, interaction)

        assert _reply(interaction) == ("Intent Statistics", "There are no intents declared for next season.")
        assert mixin.player_intents.await_args.kwargs["season_id"] == CURRENT_SEASON.id

    async def test_intent_dm_preview_says_signups_are_closed(self, mock_guild, mock_member, no_signup_season_lookup):
        mixin = _mixin(
            AdminIntentsMixIn,
            next_signup_season=no_signup_season_lookup,
            _api_conf={mock_guild.id: MagicMock()},
            _league={mock_guild.id: 1},
        )
        interaction = _interaction(mock_guild, mock_member)

        await command_callback(AdminIntentsMixIn._intents_dm_test_cmd)(mixin, interaction)

        title, _ = _reply(interaction)
        assert title == "Signups Are Closed"
