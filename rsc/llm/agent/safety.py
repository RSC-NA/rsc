"""Deterministic guards on anything the model says out loud.

The system prompt asks the model not to emit bot commands or credentials. That
is a hint, not a control: a prompt injection in a mention, a rule document or a
tool result can talk the model out of it. Everything the bot posts therefore
passes through here first, where the rules are enforced in code and cannot be
argued with.

Two risks are covered:

* **Command injection.** The bot posts into channels where other bots are
  listening. A message beginning `!ban @someone` is, to a bot that does not
  filter other bots, indistinguishable from a moderator typing it. Neutralizing
  the prefix costs nothing and removes the whole class.
* **Credential disclosure.** Keys should never reach the model at all -- they
  are constructor arguments to the client, never prompt content -- but a
  belt-and-braces redaction means a future tool that accidentally surfaces one
  cannot leak it to a channel.
"""

import re

# Characters that commonly start a bot command and are not meaningful at the
# start of a markdown line. Deliberately excludes `-`, `+`, `*`, `>`, `#`, `_`,
# `~`, `|` and `:` -- those begin lists, quotes, headers, emphasis, spoilers and
# emoji, and guarding them would mangle ordinary answers.
COMMAND_PREFIXES = "!?$%&.,;/\\=^"

# A command is a prefix bound tightly to a word: `!ban`, `.mute`, `?kick`.
# Markdown puts a space after its markers (`- item`, `> quote`), so requiring no
# space keeps legitimate formatting intact.
COMMAND_LINE_RE = re.compile(
    rf"^(?P<indent>\s*)(?P<command>[{re.escape(COMMAND_PREFIXES)}]+[A-Za-z0-9][\w-]*)",
    re.MULTILINE,
)

# Mass mentions. `allowed_mentions` already stops these from notifying anyone,
# but rendering them as plain text avoids the alarm of seeing them at all.
MASS_MENTION_RE = re.compile(r"@(everyone|here)\b")

REDACTED = "[redacted]"
ZERO_WIDTH_SPACE = "\u200b"

# High-confidence secret shapes only. Generic "long random string" matching
# would eat ballchasing group ids and RSC ids, so it is deliberately absent.
CREDENTIAL_PATTERNS: tuple[re.Pattern[str], ...] = (
    # OpenAI keys, including project/service variants.
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}"),
    # Discord bot tokens.
    re.compile(r"\b[A-Za-z0-9_-]{23,28}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}"),
    # Authorization headers and the RSC API's own scheme.
    re.compile(r"\b(?:Bearer|Api-Key)\s+[A-Za-z0-9._\-]{8,}", re.IGNORECASE),
    # Anything self-describing as a secret with a value attached.
    re.compile(
        r"\b(?:api[_ -]?key|apikey|token|secret|password|passwd)\b\s*[:=]\s*\S{6,}",
        re.IGNORECASE,
    ),
)


def neutralize_commands(text: str) -> str:
    """Wrap command-like line starts in backticks so no bot will act on them.

    Backticks rather than deletion: the answer may legitimately be *about* a
    command ("use !help"), and a code span reads correctly while being inert.
    """

    def wrap(match: re.Match[str]) -> str:
        return f"{match.group('indent')}`{match.group('command')}`"

    return COMMAND_LINE_RE.sub(wrap, text)


def redact_credentials(text: str) -> str:
    """Replace anything shaped like a secret."""
    for pattern in CREDENTIAL_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return text


def defang_mass_mentions(text: str) -> str:
    """Break `@everyone` / `@here` with an invisible separator.

    A zero-width space renders identically but stops Discord parsing the token,
    so the text still reads correctly to a human.
    """
    return MASS_MENTION_RE.sub(f"@{ZERO_WIDTH_SPACE}\\1", text)


def sanitize_response(text: str) -> str:
    """Make model output safe to post in a Discord channel.

    Applied at the single point every surface funnels through, so a new command
    or listener cannot forget it.
    """
    if not text:
        return text
    text = redact_credentials(text)
    text = neutralize_commands(text)
    return defang_mass_mentions(text)
