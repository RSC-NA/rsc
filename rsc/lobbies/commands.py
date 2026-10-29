"""Slash command bodies shared by combines and Dev League."""

import discord

from rsc.embeds import ErrorEmbed, GreenEmbed, OrangeEmbed
from rsc.lobbies.runner import LobbyLeague, LobbyRunner


async def teardown_command(interaction: discord.Interaction, runner: LobbyRunner, lobby_id: int | None) -> None:
    """End one lobby, or every open one, without the grace period."""
    guild = interaction.guild
    if not guild:
        return

    league = runner.league
    open_ids = await runner.open_lobbies(guild)
    if lobby_id is not None and lobby_id not in open_ids:
        await interaction.response.send_message(
            embed=ErrorEmbed(description=f"{league.noun.capitalize()} {lobby_id} has no live card or voice channels."),
            ephemeral=True,
        )
        return

    lobby_ids = [lobby_id] if lobby_id is not None else sorted(open_ids)
    if not lobby_ids:
        await interaction.response.send_message(
            embed=ErrorEmbed(description=f"There are no open {league.nouns} to end."),
            ephemeral=True,
        )
        return

    await interaction.response.defer(ephemeral=True)
    failed = await runner.end_now(guild, lobby_ids)
    embed = (OrangeEmbed if failed else GreenEmbed)(
        title=f"{league.name} Teardown",
        description="\n".join(ended_lines(league, lobby_ids, failed)),
    )
    await interaction.followup.send(embed=embed, ephemeral=True)


def ended_lines(league: LobbyLeague, lobby_ids: list[int], failed: list[int]) -> list[str]:
    """What `LobbyRunner.end_now` did, for a command's reply. Empty when there was nothing to end."""
    ended = [i for i in lobby_ids if i not in failed]
    lines = [f"Ended {_count(league, ended)}."] if ended else []
    if failed:
        lines.append(f"Unable to end {_count(league, failed)}. Check the bot's permissions.")
    return lines


def _count(league: LobbyLeague, lobby_ids: list[int]) -> str:
    """ "match 101", or "3 matches: 101, 102, 103"."""
    if len(lobby_ids) == 1:
        return f"{league.noun} {lobby_ids[0]}"
    return f"{len(lobby_ids)} {league.nouns}: {', '.join(map(str, lobby_ids))}"
