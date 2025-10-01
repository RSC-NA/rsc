import discord
from rsc import const

TROPHY_OPTIONS = [
    discord.SelectOption(label=f"Trophy {const.TROPHY_EMOJI}", value=const.TROPHY_EMOJI, description="Add a championship trophy"),
    discord.SelectOption(label=f"Star {const.STAR_EMOJI}", value=const.STAR_EMOJI, description="Add a star for MVP/All-Star season"),
    discord.SelectOption(
        label=f"Dev League {const.DEV_LEAGUE_EMOJI}", value=const.DEV_LEAGUE_EMOJI, description="Add a dev league championship trophy"
    ),
]


class MassTrophyModal(discord.ui.Modal, title="Mass Accolade Assignment"):
    """Modal to add accolades to multiple users by their Discord IDs"""

    member_input = discord.ui.TextInput(
        label="Discord IDs",
        placeholder="Enter Discord IDs separated by new lines",
        style=discord.TextStyle.paragraph,
        required=True,
    )

    async def on_submit(self, interaction: discord.Interaction):
        """When the modal is submitted, store the trophy count and stop the view"""

        if not interaction.guild:
            raise ValueError("This command can only be used in a server.")

        if not self.member_input.value:
            raise ValueError("Please fill in all fields.")

        # Defer for processing
        await interaction.response.defer(ephemeral=True)

    async def get_members(self, guild: discord.Guild) -> list[discord.Member]:
        """Parse the member input into a list of Discord IDs"""

        members = []
        for line in self.member_input.value.splitlines():
            discord_id = line.strip()
            if not discord_id.isdigit():
                raise ValueError(f"Discord ID is not a number: {discord_id.strip()}")

            member = guild.get_member(int(discord_id))
            if not member:
                raise ValueError(f"Member not found for Discord ID: {discord_id.strip()}")

            members.append(member)

        if not members:
            raise ValueError("No valid members found.")

        return members
