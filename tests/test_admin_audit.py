from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rsc.admin.audit import AUDIT_PAGE_CHARS, AdminAuditMixIn, audit_entry_line, audit_pages

from .utils import command_callback

WHEN = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)


def _entry(*, user=None, target=None, reason=None) -> MagicMock:
    entry = MagicMock(spec=discord.AuditLogEntry)
    entry.created_at = WHEN
    entry.user = user
    entry.target = target
    entry.reason = reason
    return entry


def _member(mention: str) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.mention = mention
    return member


class TestEntryLine:
    def test_who_did_what_to_whom_and_why(self):
        line = audit_entry_line(_entry(user=_member("<@1>"), target=_member("<@2>"), reason="spam"))

        assert line == f"{discord.utils.format_dt(WHEN, 'f')} <@1> → <@2> (spam)"

    def test_target_without_a_mention_falls_back_to_its_id(self):
        line = audit_entry_line(_entry(user=_member("<@1>"), target=discord.Object(id=42)))

        assert line.endswith("<@1> → 42")

    def test_unknown_user_and_no_target(self):
        assert audit_entry_line(_entry()) == f"{discord.utils.format_dt(WHEN, 'f')} Unknown user"


class TestPages:
    def test_short_lists_fit_one_page(self):
        assert audit_pages(["a", "b"]) == ["a\nb"]

    def test_long_lists_split_under_the_limit(self):
        lines = ["x" * 100] * 100

        pages = audit_pages(lines)

        assert len(pages) > 1
        assert all(len(p) <= AUDIT_PAGE_CHARS for p in pages)
        assert sum(p.count("x" * 100) for p in pages) == 100


class TestSearchCommand:
    @pytest.fixture
    def interaction(self) -> MagicMock:
        interaction = MagicMock(spec=discord.Interaction)
        interaction.response.defer = AsyncMock()
        interaction.response.send_message = AsyncMock()
        interaction.followup.send = AsyncMock()
        return interaction

    def _guild(self, entries) -> MagicMock:
        async def audit_logs(**kwargs):
            for entry in entries[: kwargs["limit"]]:
                yield entry

        guild = MagicMock(spec=discord.Guild)
        guild.audit_logs = MagicMock(side_effect=audit_logs)
        return guild

    async def test_replies_with_the_entries(self, interaction):
        interaction.guild = self._guild([_entry(user=_member("<@1>"), target=_member("<@2>"))])

        await command_callback(AdminAuditMixIn._admin_audit_search_cmd)(MagicMock(), interaction, action=discord.AuditLogAction.kick.value)

        assert interaction.followup.send.await_args is not None
        kwargs = interaction.followup.send.await_args.kwargs
        assert kwargs["ephemeral"] is True
        [embed] = kwargs["embeds"]
        assert embed.title == "Audit Log: kick"
        assert "<@1> → <@2>" in embed.description

    async def test_says_when_nothing_matches(self, interaction):
        interaction.guild = self._guild([])

        await command_callback(AdminAuditMixIn._admin_audit_search_cmd)(MagicMock(), interaction, action=discord.AuditLogAction.kick.value)

        assert interaction.followup.send.await_args is not None
        assert interaction.followup.send.await_args.kwargs["embed"].description == "No matching entries."

    async def test_limit_is_capped(self, interaction):
        interaction.guild = self._guild([])

        await command_callback(AdminAuditMixIn._admin_audit_search_cmd)(
            MagicMock(), interaction, action=discord.AuditLogAction.kick.value, limit=5000
        )

        assert interaction.guild.audit_logs.call_args.kwargs["limit"] == 100

    async def test_missing_audit_log_permission(self, interaction):
        async def forbidden(**kwargs):
            raise discord.Forbidden(MagicMock(status=403), "Missing Permissions")
            yield

        interaction.guild = MagicMock(spec=discord.Guild)
        interaction.guild.audit_logs = MagicMock(side_effect=forbidden)

        await command_callback(AdminAuditMixIn._admin_audit_search_cmd)(MagicMock(), interaction, action=discord.AuditLogAction.kick.value)

        assert interaction.followup.send.await_args is not None
        assert "permission" in interaction.followup.send.await_args.kwargs["embed"].description
