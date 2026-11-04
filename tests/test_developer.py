import logging
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from rsc.developer.developer import BUFMAX, DeveloperMixIn, tail_code_block
from rsc.developer.recorder import ExceptionRecorder
from rsc.embeds import BlueEmbed, ErrorEmbed

from .utils import command_callback, subcommands

LOGGER_NAME = "red.rsc.test_developer"


@pytest.fixture
def recorder():
    recorder = ExceptionRecorder()
    logger = logging.getLogger(LOGGER_NAME)
    logger.addHandler(recorder)
    yield recorder
    logger.removeHandler(recorder)


@pytest.fixture
def logger(recorder):
    return logging.getLogger(LOGGER_NAME)


def _caught(exc: BaseException) -> BaseException:
    try:
        raise exc
    except BaseException as err:
        return err


def _log_exception(logger: logging.Logger, message: str, exc: BaseException) -> None:
    try:
        raise exc
    except BaseException:
        logger.exception(message)


def _chained(depth: int) -> None:
    """Raise a chain of `depth` exceptions, so the traceback is long and doesn't collapse."""
    if depth == 0:
        raise KeyError("root cause")
    try:
        _chained(depth - 1)
    except (KeyError, RuntimeError) as err:
        raise RuntimeError(f"layer {depth}") from err


def _create_mixin(**attrs):
    saved = DeveloperMixIn.__abstractmethods__
    DeveloperMixIn.__abstractmethods__ = frozenset()
    try:
        m = object.__new__(DeveloperMixIn)
    finally:
        DeveloperMixIn.__abstractmethods__ = saved
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def _interaction(*, manage_guild: bool = True):
    interaction = MagicMock(spec=discord.Interaction)
    interaction.permissions = discord.Permissions(manage_guild=manage_guild)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()
    return interaction


def _sent(interaction) -> dict:
    interaction.response.send_message.assert_awaited_once()
    return interaction.response.send_message.await_args.kwargs


def _block_lines(content: str) -> list[str]:
    body = content.split("```", 1)[1].rsplit("```", 1)[0]
    return body.split("\n")[1:-1]


TRACEBACK_CMD = command_callback(subcommands(DeveloperMixIn._log_group)["traceback"])
TAIL_CMD = command_callback(subcommands(DeveloperMixIn._log_group)["tail"])


class TestExceptionRecorder:
    def test_captures_logger_exception(self, recorder, logger):
        _log_exception(logger, "sync failed", KeyError("x"))

        [entry] = recorder.entries()
        assert entry.logger == LOGGER_NAME
        assert entry.message == "sync failed"
        assert entry.summary == "KeyError: 'x'"
        assert entry.traceback.startswith("Traceback (most recent call last):")
        assert "_log_exception" in entry.traceback

    def test_captures_exc_info_passed_as_exception(self, recorder, logger):
        """discord.py logs task loop and view errors this way, outside the except block."""
        err = _caught(RuntimeError("view broke"))

        logger.error("Ignoring exception in view %r", "MyView", exc_info=err)

        [entry] = recorder.entries()
        assert entry.message == "Ignoring exception in view 'MyView'"
        assert entry.summary == "RuntimeError: view broke"

    def test_ignores_records_without_an_exception(self, recorder, logger):
        logger.error("plain error")
        logger.exception("exception() outside an except block")  # noqa: LOG004

        assert recorder.entries() == []

    def test_newest_first(self, recorder, logger):
        _log_exception(logger, "first", KeyError("a"))
        _log_exception(logger, "second", KeyError("b"))

        assert [e.message for e in recorder.entries()] == ["second", "first"]

    def test_keeps_only_maxlen_with_unique_ids(self, logger):
        small = ExceptionRecorder(maxlen=3)
        logger.addHandler(small)
        try:
            for i in range(5):
                _log_exception(logger, f"error {i}", ValueError(i))
        finally:
            logger.removeHandler(small)

        entries = small.entries()
        assert [e.message for e in entries] == ["error 4", "error 3", "error 2"]
        assert len({e.id for e in entries}) == 3

    def test_get_by_id(self, logger):
        small = ExceptionRecorder(maxlen=1)
        logger.addHandler(small)
        try:
            _log_exception(logger, "evicted", ValueError(1))
            evicted_id = small.entries()[0].id
            _log_exception(logger, "kept", ValueError(2))
        finally:
            logger.removeHandler(small)

        kept = small.entries()[0]
        assert small.get(kept.id) == kept
        assert small.get(evicted_id) is None


class TestTailCodeBlock:
    def test_short_text_is_not_cut(self):
        block, cut = tail_code_block("one\ntwo\n", 2000)

        assert block == "```\none\ntwo\n```"
        assert not cut

    def test_long_text_keeps_the_end_at_a_line_boundary(self):
        lines = [f"line {i:04d} " + "x" * (i % 17) for i in range(1000)]

        block, cut = tail_code_block("\n".join(lines), 300, lang="py")

        assert cut
        assert len(block) <= 300
        assert block.startswith("```py\n")
        assert block.endswith(f"{lines[-1]}\n```")
        kept = _block_lines(block)
        assert kept == lines[-len(kept) :]

    def test_backticks_in_text_cannot_close_the_block(self):
        block, _ = tail_code_block("before ``` middle ```` after", 2000)

        assert block.count("```") == 2
        assert block.startswith("```\n")
        assert block.endswith("\n```")

    def test_escaped_backticks_still_fit_the_limit(self):
        block, cut = tail_code_block("```\n" * 1000, 500)

        assert cut
        assert len(block) <= 500
        assert block.count("```") == 2


class TestTracebackCommand:
    async def test_empty_state(self, recorder):
        interaction = _interaction()

        await TRACEBACK_CMD(_create_mixin(_exception_recorder=recorder), interaction)

        kwargs = _sent(interaction)
        assert kwargs["ephemeral"] is True
        assert isinstance(kwargs["embed"], BlueEmbed)
        assert f"<t:{int(recorder.started)}:R>" in kwargs["embed"].description

    async def test_shows_newest_by_default(self, recorder, logger):
        _log_exception(logger, "older failure", KeyError("old"))
        _log_exception(logger, "newer failure", KeyError("new"))
        interaction = _interaction()

        await TRACEBACK_CMD(_create_mixin(_exception_recorder=recorder), interaction)

        kwargs = _sent(interaction)
        assert kwargs["ephemeral"] is True
        assert "file" not in kwargs
        content = kwargs["content"]
        assert content.startswith(f"**{discord.utils.escape_markdown(LOGGER_NAME)}** · <t:")
        assert "newer failure" in content
        assert content.endswith("KeyError: 'new'\n```")
        assert "old" not in content

    async def test_shows_the_chosen_exception(self, recorder, logger):
        _log_exception(logger, "older failure", KeyError("old"))
        _log_exception(logger, "newer failure", KeyError("new"))
        older = recorder.entries()[1]
        interaction = _interaction()

        await TRACEBACK_CMD(_create_mixin(_exception_recorder=recorder), interaction, str(older.id))

        assert _sent(interaction)["content"].endswith("KeyError: 'old'\n```")

    async def test_long_traceback_attaches_full_text(self, recorder, logger):
        try:
            _chained(30)
        except RuntimeError:
            logger.exception("deep failure")
        [entry] = recorder.entries()
        assert len(entry.traceback) > 2000
        interaction = _interaction()

        await TRACEBACK_CMD(_create_mixin(_exception_recorder=recorder), interaction)

        kwargs = _sent(interaction)
        assert kwargs["ephemeral"] is True
        assert len(kwargs["content"]) <= 2000
        assert kwargs["content"].endswith("RuntimeError: layer 30\n```")
        attachment = kwargs["file"]
        assert isinstance(attachment, discord.File)
        assert attachment.filename == f"traceback-{entry.id}.txt"
        text = attachment.fp.read().decode()
        assert "deep failure" in text
        assert entry.traceback in text

    async def test_long_message_still_fits(self, recorder, logger):
        _log_exception(logger, "m" * 5000, KeyError("x"))
        interaction = _interaction()

        await TRACEBACK_CMD(_create_mixin(_exception_recorder=recorder), interaction)

        assert len(_sent(interaction)["content"]) <= 2000

    @pytest.mark.parametrize("value", ["999", "not-an-id"])
    async def test_unknown_exception_is_an_error(self, recorder, logger, value):
        _log_exception(logger, "failure", KeyError("x"))
        interaction = _interaction()

        await TRACEBACK_CMD(_create_mixin(_exception_recorder=recorder), interaction, value)

        kwargs = _sent(interaction)
        assert kwargs["ephemeral"] is True
        assert isinstance(kwargs["embed"], ErrorEmbed)


class TestTracebackAutocomplete:
    async def test_lists_newest_first_with_ids(self, recorder, logger):
        _log_exception(logger, "a", KeyError("first"))
        _log_exception(logger, "b", KeyError("second"))
        newest, oldest = recorder.entries()

        choices = await DeveloperMixIn._traceback_autocomplete(_create_mixin(_exception_recorder=recorder), _interaction(), "")

        assert [c.value for c in choices] == [str(newest.id), str(oldest.id)]
        assert choices[0].name.endswith(f"s ago · {LOGGER_NAME} · KeyError: 'second'")

    async def test_filters_by_current_text(self, recorder, logger):
        _log_exception(logger, "a", KeyError("first"))
        _log_exception(logger, "b", ValueError("second"))

        choices = await DeveloperMixIn._traceback_autocomplete(_create_mixin(_exception_recorder=recorder), _interaction(), "valueerror")

        assert [c.name.rsplit(" · ", 1)[1] for c in choices] == ["ValueError: second"]

    async def test_names_fit_discord_limit(self, recorder, logger):
        _log_exception(logger, "a", KeyError("k" * 300))

        [choice] = await DeveloperMixIn._traceback_autocomplete(_create_mixin(_exception_recorder=recorder), _interaction(), "")

        assert len(choice.name) <= 100

    async def test_hidden_without_manage_guild(self, recorder, logger):
        _log_exception(logger, "a", KeyError("x"))

        choices = await DeveloperMixIn._traceback_autocomplete(
            _create_mixin(_exception_recorder=recorder), _interaction(manage_guild=False), ""
        )

        assert choices == []


class TestTailCommand:
    async def test_missing_handler_reply_is_ephemeral(self):
        mixin = _create_mixin(get_latest_log_file=AsyncMock(return_value=None))
        interaction = _interaction()

        await TAIL_CMD(mixin, interaction)

        kwargs = _sent(interaction)
        assert kwargs["ephemeral"] is True
        assert isinstance(kwargs["embed"], ErrorEmbed)

    async def test_drops_the_partial_first_line(self, tmp_path):
        lines = [f"2026-11-04 12:00:{i:02d} INFO red.rsc line {i:04d}" for i in range(200)]
        log_file = tmp_path / "latest.log"
        log_file.write_text("".join(f"{line}\n" for line in lines))
        mixin = _create_mixin(get_latest_log_file=AsyncMock(return_value=str(log_file)))
        interaction = _interaction()

        await TAIL_CMD(mixin, interaction)

        content = _sent(interaction)["content"]
        assert len(content) <= 2000
        shown = _block_lines(content)
        assert shown == lines[-len(shown) :]
        assert shown[-1] == lines[-1]

    async def test_keeps_a_first_line_that_starts_on_the_boundary(self, tmp_path):
        tail = "".join(f"line {i:03d} {'y' * 90}\n" for i in range(19))
        boundary_line = "z" * (BUFMAX - len(tail) - 1)
        log_file = tmp_path / "latest.log"
        log_file.write_text(f"older line\n{boundary_line}\n{tail}")
        mixin = _create_mixin(get_latest_log_file=AsyncMock(return_value=str(log_file)))
        interaction = _interaction()

        await TAIL_CMD(mixin, interaction)

        assert _block_lines(_sent(interaction)["content"])[0] == boundary_line
