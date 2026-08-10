"""Tests for how a mention declined by the spend controls is reported.

The declined path used to add a bare reaction and return, which is
indistinguishable from the bot being broken -- the asker saw a typing
indicator, then an hourglass, and never learned a cooldown was the reason.
"""

import re
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rsc.llm.agent.service import BudgetError, BudgetVerdict
from rsc.llm.llm import LLM_DECLINE_NOTICE_SECONDS, LLMMixIn


def declined(reason: str, retry_after: float = 0.0) -> BudgetError:
    return BudgetError(BudgetVerdict(allowed=False, reason=reason, retry_after=retry_after))


def notice(reason: str, retry_after: float = 0.0) -> str:
    return LLMMixIn._budget_notice(declined(reason, retry_after))


async def decline(message, exc: BudgetError) -> None:
    """Call the decline handler without instantiating the full cog."""
    await LLMMixIn._decline_mention(message, exc)


@pytest.fixture
def message():
    mock = MagicMock(spec=discord.Message)
    mock.reply = AsyncMock()
    mock.add_reaction = AsyncMock()
    return mock


def retry_offset(text: str) -> int:
    """Seconds from now to the relative timestamp Discord will render."""
    match = re.search(r"<t:(\d+):R>", text)
    assert match, f"no relative timestamp in {text!r}"
    return int(match.group(1)) - int(discord.utils.utcnow().timestamp())


class TestBudgetNotice:
    def test_cooldown_names_the_wait(self):
        """Discord renders <t:...:R> as a live "in 5 seconds" countdown."""
        assert retry_offset(notice("cooldown", retry_after=4.2)) == 5

    def test_a_sub_second_wait_never_rounds_to_zero(self):
        """A timestamp already in the past would render as "0 seconds ago"."""
        assert retry_offset(notice("cooldown", retry_after=0.3)) == 1

    def test_user_and_guild_caps_are_distinguishable(self):
        assert notice("user_cap") != notice("guild_cap")
        assert "today" in notice("user_cap")
        assert "today" in notice("guild_cap")


class TestDeclineMention:
    async def test_replies_with_a_self_deleting_notice(self, message):
        exc = declined("cooldown", retry_after=4.2)

        await decline(message, exc)

        message.reply.assert_awaited_once()
        kwargs = message.reply.await_args.kwargs
        assert retry_offset(kwargs["content"]) == 5
        assert kwargs["delete_after"] == LLM_DECLINE_NOTICE_SECONDS
        # Model-free text, but the asker is replied to, so still pinged by
        # nobody but the reply itself.
        assert kwargs["allowed_mentions"].everyone is False

    @pytest.mark.parametrize(
        ("reason", "emoji"),
        [
            ("cooldown", "\N{HOURGLASS WITH FLOWING SAND}"),
            ("user_cap", "\N{BAR CHART}"),
            ("guild_cap", "\N{NO ENTRY SIGN}"),
        ],
    )
    async def test_each_reason_gets_its_own_mark(self, message, reason, emoji):
        await decline(message, declined(reason))

        message.add_reaction.assert_awaited_once_with(emoji)

    async def test_notice_survives_a_failed_reaction(self, message):
        """Reacting needs a permission that replying does not."""
        message.add_reaction.side_effect = discord.HTTPException(MagicMock(), "no perms")

        await decline(message, declined("cooldown", retry_after=1.0))

        message.reply.assert_awaited_once()

    async def test_a_failed_reply_is_not_fatal(self, message):
        message.reply.side_effect = discord.HTTPException(MagicMock(), "no perms")

        await decline(message, declined("guild_cap"))

        message.add_reaction.assert_awaited_once()


class TestBotAuthors:
    async def test_other_bots_never_reach_the_agent(self):
        """Two bots mentioning each other would otherwise trade agent runs."""
        message = MagicMock(spec=discord.Message)
        message.author.bot = True
        cog = MagicMock()
        cog._get_llm_status = AsyncMock(return_value=True)

        await LLMMixIn.llm_reply_to_mention(cog, message)

        cog._get_llm_status.assert_not_awaited()
