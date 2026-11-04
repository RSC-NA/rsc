import json
import random
import string
from collections.abc import Callable, Coroutine
from http import HTTPStatus
from types import SimpleNamespace
from typing import Any, TypeVar

import discord
from discord import app_commands
from rscapi.exceptions import ApiException

from rsc.exceptions import ApiError

T = TypeVar("T")


def random_string(length=8):
    """Generate a random alphanumeric string of given length."""

    letters_and_digits = string.ascii_letters
    return "".join(random.choice(letters_and_digits) for i in range(length))


def generate_discord_id():
    """Generate a random Discord ID (17-19 digit integer)."""
    return random.randint(10**16, 9223372036854775807)


def command_callback(cmd: app_commands.Command[Any, ..., T]) -> Callable[..., Coroutine[Any, Any, T]]:
    """An app command's callback, to call with an explicit mixin `self`.

    discord.py types `Command.callback` as a union of the with-self and
    without-self signatures, and no single call satisfies both.
    """
    return cmd.callback


def subcommands(group: app_commands.Group) -> dict[str, app_commands.Command[Any, ..., Any]]:
    """A group's direct subcommands by name, leaving out nested groups."""
    return {c.name: c for c in group.commands if isinstance(c, app_commands.Command)}


def custom_ids(view: discord.ui.View) -> list[str]:
    """The custom ids of a view's children, in order. Every child must have one."""
    ids: list[str] = []
    for child in view.children:
        if isinstance(child, discord.ui.DynamicItem):
            ids.append(child.custom_id)
        else:
            assert isinstance(child, discord.ui.Button), child
            assert child.custom_id is not None, child
            ids.append(child.custom_id)
    return ids


def api_exception(
    status: int, message: str = "boom", *, error_type: str = "APIException", extra: dict[str, Any] | None = None
) -> ApiException:
    """`ApiException.from_response` raises the status subclass (`NotFoundException` for a 404) instead of returning it."""
    body = json.dumps({"message": message, "extra": extra or {}, "type": error_type, "status_code": status})
    http_resp = SimpleNamespace(status=status, reason=HTTPStatus(status).phrase, data=body.encode(), headers={})
    try:
        ApiException.from_response(http_resp=http_resp, body=body, data=None)
    except ApiException as exc:
        return exc
    raise AssertionError("ApiException.from_response always raises")


def api_error(status: int, message: str = "boom", **kwargs: Any) -> ApiError:
    return ApiError.from_exception(api_exception(status, message, **kwargs))
