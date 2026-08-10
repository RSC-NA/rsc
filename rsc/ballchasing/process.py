import asyncio
import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import md5
from io import BytesIO
from pathlib import Path

import ballchasing
import discord
from replay_parser import ReplayParser
from replay_parser.models import Replay as ParsedReplay

from rsc.logs import GuildLogAdapter

logger = logging.getLogger("red.rsc.ballchasing.process")
log = GuildLogAdapter(logger)

# Disable debug logging in replay_parser (large amount of data)
logging.getLogger("replay_parser").setLevel(logging.INFO)

# The match GUID identifies a lobby session, NOT a single game. Teams that play
# a whole series without leaving the lobby produce one GUID for every game in it
# (confirmed against production: two games with different rosters, durations and
# scores sharing 446406F211F1692A755163A95FFA4FCB). So the GUID narrows a game
# down to a lobby and nothing more -- it is one component of the fingerprint
# below, never an identity on its own.
#
# The header key was renamed in game build 241014: current builds write
# "MatchGUID", a handful of older ones write "MatchGuid", older ones have
# neither. A missing GUID just makes the fingerprint slightly less specific.
MATCH_GUID_KEYS = ("MatchGUID", "MatchGuid")

# (replay header property, ballchasing core stat attribute)
STAT_FIELDS = (
    ("Score", "score"),
    ("Goals", "goals"),
    ("Assists", "assists"),
    ("Saves", "saves"),
    ("Shots", "shots"),
)


class ReplayParseError(ValueError):
    """A submitted file could not be read as a Rocket League replay."""

    def __init__(self, label: str):
        self.label = label
        super().__init__(f"`{label}` could not be parsed as a Rocket League replay file.")


@dataclass(slots=True)
class ReplayCandidate:
    """A replay the user submitted, read and parsed exactly once.

    `data` is the only copy of the file bytes we keep. Validation, duplicate
    detection and the upload all read from it, so an attachment is fetched from
    Discord's CDN a single time.
    """

    label: str  # filename, used in user facing errors
    data: bytes
    parsed: ParsedReplay
    match_guid: str | None
    fingerprint: str | None  # identity of the game, shared across recordings
    digest: str  # md5 hex


@dataclass(slots=True)
class CollisionReport:
    upload: list[ReplayCandidate] = field(default_factory=list)
    # candidate -> id of the ballchasing replay it collided with, when known
    duplicates: list[tuple[ReplayCandidate, str | None]] = field(default_factory=list)


@dataclass(slots=True)
class UploadOutcome:
    candidate: ReplayCandidate
    replay_id: str | None = None
    duplicate: bool = False
    error: str | None = None


@dataclass(slots=True)
class ReplayUploadResult:
    """What actually happened to every replay the reporter submitted."""

    group: str
    outcomes: list[UploadOutcome] = field(default_factory=list)

    @property
    def uploaded(self) -> int:
        return sum(1 for o in self.outcomes if o.replay_id and not o.duplicate)

    @property
    def skipped(self) -> int:
        return sum(1 for o in self.outcomes if o.duplicate)

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.error)

    @property
    def errors(self) -> list[UploadOutcome]:
        return [o for o in self.outcomes if o.error]

    @property
    def replay_ids(self) -> list[str]:
        return [o.replay_id for o in self.outcomes if o.replay_id]


def match_guid(parsed: ParsedReplay) -> str | None:
    """Read the lobby session GUID out of a parsed replay header, if it has one."""
    for key in MATCH_GUID_KEYS:
        value = parsed.header.get_property(key)
        if isinstance(value, str) and value:
            return value.upper()
    return None


def _stat(value: object) -> str:
    """Canonical numeric string. Ballchasing returns floats, replay headers ints."""
    try:
        return str(round(float(value)))  # ty: ignore[invalid-argument-type]
    except (TypeError, ValueError):
        return "?"


def _digest_players(players: list[str]) -> str | None:
    if not players:
        return None
    return md5("|".join(sorted(players)).encode()).hexdigest()


def local_fingerprint(parsed: ParsedReplay) -> str | None:
    """Identity of a single game, derived from a locally parsed replay.

    Every player's recording of one game agrees on the final box score, so this
    is stable across recordings. It deliberately uses:

    - no timestamps, because clients save replays seconds apart and may be in
      different timezones
    - no match GUID, because a whole series played in one lobby shares one GUID,
      and because the local header and ballchasing are two separate sources for
      it. A format disagreement between them would silently disable dedup
      entirely, which is far worse than the collision it would protect against
      (two different games with identical box scores for all six players).
    """
    lines = []
    for player in parsed.player_stats or []:
        name = player.get("Name")
        if name is None:
            return None
        lines.append(":".join([str(name), *[_stat(player.get(prop)) for prop, _ in STAT_FIELDS]]))
    return _digest_players(lines)


def bc_fingerprint(replay: ballchasing.models.Replay) -> str | None:
    """`local_fingerprint` computed from a ballchasing replay.

    Returns None when the replay cannot be compared: still processing, failed to
    parse, or missing per player stats.
    """
    if replay.status is not None and replay.status != ballchasing.ReplayStatus.OK:
        return None

    lines = []
    for team in (replay.blue, replay.orange):
        if not (team and team.players):
            return None
        for player in team.players:
            core = player.stats.core if player.stats else None
            if core is None:
                return None
            lines.append(":".join([str(player.name), *[_stat(getattr(core, attr, None)) for _, attr in STAT_FIELDS]]))
    return _digest_players(lines)


def _parse_bytes(data: bytes) -> ParsedReplay:
    """Parse replay bytes. Synchronous and CPU bound. Call via `asyncio.to_thread`."""
    # ReplayParser is stateful, so it is not shared between calls.
    return ReplayParser(debug=False).parse(replay_file=BytesIO(data), net_stream=False)


async def _read_source(source: discord.Attachment | str | bytes) -> tuple[str, bytes]:
    if isinstance(source, discord.Attachment):
        return source.filename, await source.read()
    if isinstance(source, bytes):
        return f"replay-{md5(source).hexdigest()[:8]}", source
    if isinstance(source, str):
        path = Path(source)
        return path.name, await asyncio.to_thread(path.read_bytes)
    # Not reachable through the annotated types, but a mistyped caller should
    # fail loudly rather than have str(source) treated as a file path.
    raise TypeError(f"Unsupported replay source: {type(source).__name__}")


async def build_candidates(sources: Sequence[discord.Attachment | str | bytes]) -> list[ReplayCandidate]:
    """Read and parse every submitted replay once.

    Raises `ReplayParseError` naming the offending file if one of them is not a
    readable replay.
    """
    reads = await asyncio.gather(*(_read_source(s) for s in sources))

    candidates: list[ReplayCandidate] = []
    for label, data in reads:
        # Parsing is pure Python and GIL bound, so running these concurrently
        # buys nothing. The thread is only here to keep the gateway heartbeat
        # alive while we chew through the header.
        try:
            parsed = await asyncio.to_thread(_parse_bytes, data)
        except Exception as exc:
            log.warning(f"Unable to parse replay {label}: {exc}")
            raise ReplayParseError(label) from exc

        candidates.append(
            ReplayCandidate(
                label=label,
                data=data,
                parsed=parsed,
                match_guid=match_guid(parsed),
                fingerprint=local_fingerprint(parsed),
                digest=md5(data).hexdigest(),
            )
        )
    return candidates


def duplicate_in_batch(candidates: Sequence[ReplayCandidate]) -> ReplayCandidate | None:
    """Return the first candidate that repeats an earlier one in the same submission.

    Byte identical files are caught by the digest. Two different players'
    recordings of the same game have different bytes but the same fingerprint.

    This must not key on the match GUID: a series played without leaving the
    lobby gives every game the same GUID, so that would reject the whole
    submission.
    """
    seen_digests: set[str] = set()
    seen_fingerprints: set[str] = set()
    for candidate in candidates:
        if candidate.digest in seen_digests:
            return candidate
        seen_digests.add(candidate.digest)

        if candidate.fingerprint:
            if candidate.fingerprint in seen_fingerprints:
                return candidate
            seen_fingerprints.add(candidate.fingerprint)
    return None


async def replay_group_collisions(
    candidates: Sequence[ReplayCandidate],
    bc_replays: Iterable[ballchasing.models.Replay],
    ledger: Mapping[str, str] | None = None,
) -> CollisionReport:
    """Split candidates into "already in the group" and "needs uploading".

    `ledger` maps fingerprint to ballchasing replay id for replays this bot
    uploaded to the group recently. It covers the window where ballchasing has
    accepted a replay but not finished processing it, so the group listing
    exposes neither its stats nor its match GUID.
    """
    ledger = ledger or {}

    # fingerprint -> the ballchasing replay already holding that game
    known: dict[str, str] = {}
    for bc in bc_replays:
        # A failed replay is unusable to ballchasing, so it must not block a
        # good copy of the same game.
        if bc.status == ballchasing.ReplayStatus.FAILED:
            continue
        fingerprint = bc_fingerprint(bc)
        if fingerprint:
            known.setdefault(fingerprint, bc.id)

    for fingerprint, replay_id in ledger.items():
        known.setdefault(fingerprint, replay_id)

    report = CollisionReport()
    for candidate in candidates:
        # No fingerprint means no player data to compare, so we cannot tell.
        # Upload it: an extra replay is recoverable, a dropped one is not.
        existing = known.pop(candidate.fingerprint, None) if candidate.fingerprint else None
        if existing is None:
            report.upload.append(candidate)
            continue
        log.debug(f"Skipping duplicate replay {candidate.label} (existing: {existing})")
        report.duplicates.append((candidate, existing))
    return report
