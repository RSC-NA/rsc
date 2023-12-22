import time

import discord
from rscapi.models.match import Match
from rscapi.models.tier import Tier

from rsc.embeds import BlueEmbed
from rsc.utils import utils
from rsc.views import AuthorOnlyView, CancelButton


class BallchasingProcessingView(AuthorOnlyView):
    def __init__(
        self,
        interaction: discord.Interaction,
        matches: list[Match],
        tiers: list[Tier],
        channel: discord.TextChannel,
        role: discord.Role | None = None,
        timeout: float = 0,
    ):
        if not interaction.guild:
            raise ValueError("Interaction must originate from a guild.")

        super().__init__(interaction=interaction, timeout=timeout)
        self.channel: discord.TextChannel = channel
        self.cancelled: bool = False
        self.completed: bool = False
        self.guild: discord.Guild = interaction.guild
        self.matches: list[Match] = matches
        self.msg: discord.Message | None = None
        self.next: list[Match] = []
        self.status: dict[str, int] = {}
        self.start_time = time.time()
        self.role: discord.Role | None = role
        self.tiers: list[Tier] = tiers
        self.tier_groups: dict[str, str | None] = {}
        self.totals: dict[str, int] = {}
        self.add_item(CancelButton())

        self.tiers.sort(key=lambda x: x.position, reverse=True)

        for m in self.matches:
            tier = m.home_team.tier
            if not self.tier_groups.get(tier):
                self.tier_groups[tier] = None
            if not self.status.get(tier):
                self.status[tier] = 0
            if not self.totals.get(tier):
                self.totals[tier] = 0
            self.totals[tier] += 1

    async def build_embed(self):
        embed = BlueEmbed(title="Replay Processing Report")

        desc = []
        for t in self.tiers:
            if not t.name:
                raise ValueError(f"Tier provided does not have a name. ID: {t.id}")
            trole = await utils.get_tier_role(self.guild, t.name)
            tfmt = trole.mention if trole else f"**{t.name}**"

            status_num = self.status.get(t.name, 0)
            total_num = self.totals.get(t.name, 0)

            summary = f"{tfmt} ({status_num}/{total_num})"

            # Processing status marker
            if not (self.cancelled or self.completed) and status_num != total_num:
                summary += " _[Processing]_"

            # Ballchasing Group Link
            if self.tier_groups.get(t.name):
                summary += f" [View Group]({self.tier_groups[t.name]})"

            # Show matches being currently searched
            for n in self.next:
                if n.home_team.tier == t.name:
                    summary += f"\n_Searching {n.home_team.name} vs {n.away_team.name}_"

            desc.append(summary)

        if self.completed:
            num_completed = await self.completed_matches()
            total_matches = len(self.matches)
            if num_completed == total_matches:
                desc.append(
                    f"\n **All matches have been successfully reported. ({num_completed}/{total_matches})**"
                )
            else:
                desc.append(
                    f"\n **Some matches could not be found. ({num_completed}/{total_matches})**"
                )
            exc_time = await self.execution_time()
            embed.set_footer(text=f"Completed in {exc_time}")

        if self.cancelled:
            num_completed = await self.completed_matches()
            total_matches = len(self.matches)
            desc.append(
                f"\n **User has cancelled replay processing. ({num_completed}/{total_matches})**"
            )
            exc_time = await self.execution_time()
            embed.set_footer(text=f"Cancelled after {exc_time}")

        embed.description = "\n".join(desc)

        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)

        return embed

    async def completed_matches(self) -> int:
        total = 0
        for v in self.status.values():
            total += v
        return total

    async def execution_time(self) -> str:
        et = time.time()
        exc_time = et - self.start_time
        return f"{round(exc_time // 60)}m {round(exc_time % 60)}s"

    async def next_batch(self, matches: list[Match]):
        self.next = matches
        await self.prompt()

    async def update(self, matches: list[Match]):
        for m in matches:
            self.status[m.home_team.tier] += 1
        await self.prompt()

    async def prompt(self):
        view = None
        embed = await self.build_embed()

        if self.role:
            content = self.role.mention

        if not (self.completed or self.cancelled):
            view = self

        if self.msg:
            await self.msg.edit(embed=embed, view=view)
        else:
            content = self.role.mention if self.role else ""
            self.msg = await self.channel.send(content=content, embed=embed, view=view)

    async def finished(self):
        self.next = []
        self.completed = True
        await self.prompt()
        self.stop()

    async def decline(self, interaction: discord.Interaction):
        await interaction.response.defer()
        self.cancelled = True
        await self.prompt()
        self.stop()
