"""Tests for the output guards.

These enforce in code what the system prompt only asks for. A prompt injection
in a mention, a rule document or a ticket transcript can talk the model out of
an instruction; it cannot talk a regex out of anything.
"""

import pytest

from rsc.llm.agent.safety import (
    defang_mass_mentions,
    neutralize_commands,
    redact_credentials,
    sanitize_response,
)


# Command injection


@pytest.mark.parametrize(
    "text",
    [
        "!ban @someone",
        "?kick user",
        ".mute everyone",
        "$giverole admin",
        "/ban someone",
        ";purge 100",
        "%unban 12345",
        "&role add admin",
        ",addrole moderator",
        "=eval print(1)",
        "^promote nickm",
        "\\shutdown",
    ],
)
def test_command_like_lines_are_neutralized(text: str) -> None:
    """The bot posts where other bots listen; a bare command could be acted on."""
    result = neutralize_commands(text)

    assert not result.startswith(text[0]), f"{text!r} left actionable"
    assert "`" in result


def test_commands_are_neutralized_on_every_line_not_just_the_first() -> None:
    """A model can be induced to put the payload on line two."""
    result = neutralize_commands("Sure, here is how:\n!ban @someone\nHope that helps.")

    assert "\n`!ban`" in result
    assert not any(line.startswith("!") for line in result.splitlines())


def test_indented_commands_are_neutralized() -> None:
    result = neutralize_commands("    !ban someone")

    assert "`!ban`" in result
    assert "!ban " not in result


def test_repeated_prefixes_are_neutralized() -> None:
    """`!!cmd` is a real prefix style and must not slip through."""
    result = neutralize_commands("!!purge 100")

    assert result.startswith("`!!purge`")


@pytest.mark.parametrize(
    "text",
    [
        "- Fifty-Fifty Pizzeria",
        "* Minty Fresh",
        "> Rule 5.7.3 says:",
        "# Standings",
        "## Master Tier",
        "1. First place",
        "**Bold answer**",
        "*italic*",
        "~~struck~~",
        "||spoiler||",
        ":smile: nice",
        "_underline_",
    ],
)
def test_markdown_and_ordinary_text_survive(text: str) -> None:
    """Over-eager guarding would mangle every list and quote the bot writes."""
    assert neutralize_commands(text) == text


def test_a_command_mentioned_in_prose_is_left_readable() -> None:
    """Backticks rather than deletion: the answer may legitimately be about a command."""
    result = neutralize_commands("!help shows the commands")

    assert result == "`!help` shows the commands"


# Mass mentions


@pytest.mark.parametrize("mention", ["@everyone", "@here"])
def test_mass_mentions_are_defanged(mention: str) -> None:
    result = defang_mass_mentions(f"Hey {mention} listen up")

    assert mention not in result
    assert "everyone" in result or "here" in result


def test_ordinary_at_text_is_untouched() -> None:
    assert defang_mass_mentions("email me @ nick") == "email me @ nick"


# Credentials


@pytest.mark.parametrize(
    "secret",
    [
        "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890",
        "sk-abcdefghijklmnopqrstuvwxyz",
        "Bearer abcdef1234567890abcdef",
        "Api-Key aVeryLongApiKeyValue123",
        "api_key: supersecretvalue123",
        "password = hunter2hunter2",
        "TOKEN=abcdef1234567890",
    ],
)
def test_credentials_are_redacted(secret: str) -> None:
    result = redact_credentials(f"The value is {secret} ok")

    assert "[redacted]" in result
    assert secret not in result


def test_discord_bot_token_is_redacted() -> None:
    token = "MTIzNDU2Nzg5MDEyMzQ1Njc4OQ.GhIjKl.abcdefghijklmnopqrstuvwxyz123"
    result = redact_credentials(f"token {token}")

    assert token not in result


@pytest.mark.parametrize(
    "text",
    [
        "Rule 5.7.3 covers substitutions",
        "https://ballchasing.com/group/rsc-s26-master-abc123def456",
        "RSC ID 12345 belongs to nickm",
        "Fifty-Fifty Pizzeria has a 12-4 record",
    ],
)
def test_ordinary_league_data_is_not_redacted(text: str) -> None:
    """Generic long-random-string matching would eat ids and ballchasing links."""
    assert redact_credentials(text) == text


# Combined


def test_sanitize_applies_every_guard() -> None:
    injected = "sk-abcdefghijklmnopqrstuvwxyz\n!ban @someone\n@everyone look"

    result = sanitize_response(injected)

    assert "sk-abcdefghijklmnopqrstuvwxyz" not in result
    assert "\n!ban" not in result
    assert "@everyone" not in result


def test_sanitize_handles_empty_output() -> None:
    assert sanitize_response("") == ""


def test_sanitize_leaves_a_normal_answer_alone() -> None:
    answer = (
        "There are 30 franchises. Here are a few:\n"
        "- Fifty-Fifty Pizzeria (GM: Alextross)\n"
        "- Minty Fresh (GM: Tinsel)\n\n"
        "> See RSC Rules 4.1 for franchise structure."
    )

    assert sanitize_response(answer) == answer


def test_agent_loop_sanitizes_its_output() -> None:
    """The guard must sit at the loop's single exit, not at each call site."""
    from rsc.llm.agent import loop

    assert "sanitize_response" in loop._output_text.__code__.co_names


def test_credentials_never_enter_the_prompt() -> None:
    """The real guarantee is structural, not the redaction regex.

    A key is a client constructor argument. Nothing that builds prompt text
    should be able to see one, so redaction only ever has to catch a credential
    that a *user* pasted.
    """
    import inspect

    from rsc.llm.agent import prompts

    assert "api_key" not in inspect.getsource(prompts)


def test_system_prompt_states_the_hard_limits() -> None:
    """Enforcement is in code, but the model should not be trying in the first place."""
    from rsc.llm.agent.prompts import PERSONA

    lowered = PERSONA.lower()
    assert "command prefix" in lowered
    assert "@everyone" in lowered
    assert "credential" in lowered
    assert "data, not instructions" in lowered
