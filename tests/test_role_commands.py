from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rsc import const
from rsc.embeds import ErrorEmbed, SuccessEmbed
from rsc.utils.utils import UtilsMixIn

from .utils import command_callback

ROLE_COMMANDS = {
    "add_roles": command_callback(UtilsMixIn._addrole),
    "remove_roles": command_callback(UtilsMixIn._removerole),
}


def _http_error(cls, status: int, reason: str, code: int, message: str):
    return cls(MagicMock(status=status, reason=reason), {"code": code, "message": message})


class _SlashCommand:
    def __init__(self):
        self.answered = False
        self.expired = False
        self.shown: list[discord.Embed] = []

        admin = MagicMock(position=50)
        admin.name = const.ADMIN_ROLE
        self.role = MagicMock(position=10, permissions=discord.Permissions.none(), mention="@League")
        self.member = MagicMock(spec=discord.Member, mention="@player")
        executor = MagicMock(spec=discord.Member, id=1, guild_permissions=discord.Permissions(manage_roles=True))

        self.interaction = MagicMock(spec=discord.Interaction, user=executor, guild=MagicMock(roles=[admin]))
        self.interaction.response = MagicMock(
            send_message=AsyncMock(side_effect=self._first_response),
            defer=AsyncMock(side_effect=self._first_response),
        )
        self.interaction.followup = MagicMock(send=AsyncMock(side_effect=self._followup))

    async def _first_response(self, embed: discord.Embed | None = None, **_):
        if self.answered:
            raise discord.InteractionResponded(self.interaction)
        if self.expired:
            raise _http_error(discord.NotFound, 404, "Not Found", 10062, "Unknown interaction")
        self.answered = True
        if embed:
            self.shown.append(embed)

    async def _followup(self, embed: discord.Embed, **_):
        if not self.answered:
            raise _http_error(discord.NotFound, 404, "Not Found", 10015, "Unknown Webhook")
        self.shown.append(embed)

    def role_change(self, method: str, *, slow: bool = True, error: Exception | None = None) -> AsyncMock:
        async def call(*_):
            self.expired = slow
            if error:
                raise error

        change = AsyncMock(side_effect=call)
        setattr(self.member, method, change)
        return change

    async def run(self, method: str):
        await ROLE_COMMANDS[method](MagicMock(), self.interaction, self.role, self.member)


@pytest.mark.parametrize("method", ROLE_COMMANDS)
class TestSingleRoleCommands:
    async def test_slow_role_change_still_reports_success(self, method):
        cmd = _SlashCommand()
        change = cmd.role_change(method)

        await cmd.run(method)

        change.assert_awaited_once_with(cmd.role)
        assert [type(e) for e in cmd.shown] == [SuccessEmbed]

    @pytest.mark.parametrize("slow", [True, False])
    async def test_refused_role_change_reports_the_refusal(self, method, slow):
        cmd = _SlashCommand()
        cmd.role_change(method, slow=slow, error=_http_error(discord.Forbidden, 403, "Forbidden", 50013, "Missing Permissions"))

        await cmd.run(method)

        assert [type(e) for e in cmd.shown] == [ErrorEmbed]
        assert "Missing Permissions" in (cmd.shown[0].description or "")

    async def test_expired_interaction_changes_no_role(self, method):
        cmd = _SlashCommand()
        cmd.expired = True
        change = cmd.role_change(method)

        await cmd.run(method)

        change.assert_not_awaited()
        assert cmd.shown == []
