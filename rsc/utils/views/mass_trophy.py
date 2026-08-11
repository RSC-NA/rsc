import logging

import discord

from rsc import const

log = logging.getLogger("red.rsc.utils.views")

TROPHY_OPTIONS = [
    discord.SelectOption(label=f"Trophy {const.TROPHY_EMOJI}", value=const.TROPHY_EMOJI, description="Add a championship trophy"),
    discord.SelectOption(label=f"Star {const.STAR_EMOJI}", value=const.STAR_EMOJI, description="Add a star for MVP/All-Star season"),
    discord.SelectOption(
        label=f"Dev League {const.DEV_LEAGUE_EMOJI}", value=const.DEV_LEAGUE_EMOJI, description="Add a dev league championship trophy"
    ),
]

# A mass assignment can run for a while. Give the operator plenty of time to
# paste a list, but don't wait forever if they dismiss the modal.
MODAL_TIMEOUT = 600.0


class MassTrophyModal(discord.ui.Modal, title="Mass Accolade Assignment"):
    """Modal to add accolades to multiple users by their Discord IDs"""

    member_input = discord.ui.TextInput(
        label="Discord IDs",
        placeholder="Enter Discord IDs separated by new lines",
        style=discord.TextStyle.paragraph,
        required=True,
    )

    def __init__(self, timeout: float | None = MODAL_TIMEOUT):
        super().__init__(timeout=timeout)
        # Submit interaction, stored so the caller can report progress against
        # the response deferred below instead of leaving it spinning forever.
        self.interaction: discord.Interaction | None = None

    async def on_submit(self, interaction: discord.Interaction):
        """When the modal is submitted, store the trophy count and stop the view"""

        if not interaction.guild:
            raise ValueError("This command can only be used in a server.")

        if not self.member_input.value:
            raise ValueError("Please fill in all fields.")

        self.interaction = interaction

        # Defer for processing. `thinking=True` is required: without it a modal
        # submit is acknowledged with a message *update*, which creates no
        # message for the caller to edit progress into.
        await interaction.response.defer(ephemeral=True, thinking=True)

    async def get_members(self, guild: discord.Guild) -> tuple[list[discord.Member], list[str]]:
        """Resolve the submitted Discord IDs to guild members.

        Unresolvable lines are collected and returned instead of raised so that
        one bad ID does not discard the rest of the batch.

        Returns:
            A tuple of (resolved members, error messages).

        Raises:
            ValueError: No Discord IDs were submitted at all.
        """

        members: list[discord.Member] = []
        errors: list[str] = []

        for line in self.member_input.value.splitlines():
            discord_id = line.strip()
            if not discord_id:
                continue

            if not discord_id.isdigit():
                errors.append(f"Not a valid Discord ID: `{discord_id}`")
                continue

            member = guild.get_member(int(discord_id))
            if member:
                members.append(member)
                continue

            # `get_member()` only reads the cache. Fall back to the API so an
            # uncached member isn't mistaken for one who isn't in the guild.
            try:
                member = await guild.fetch_member(int(discord_id))
            except discord.NotFound:
                errors.append(f"Member not found in guild: `{discord_id}`")
                continue
            except discord.HTTPException as exc:
                log.warning(f"Error fetching member {discord_id}: {exc}")
                errors.append(f"Error fetching member `{discord_id}`: {exc.text or exc.status}")
                continue

            members.append(member)

        if not members and not errors:
            raise ValueError("No Discord IDs were submitted.")

        return members, errors
