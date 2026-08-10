"""Ballchasing replay upload: group resolution, locking, and duplicate detection.

The behaviour these protect is the two-reporters-at-once case: both players in a
match run /reportmatch within seconds of each other, and the group must end up
with exactly one copy of each game under exactly one group tree.
"""

import asyncio
from hashlib import md5
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import ballchasing
import discord
import pytest
from ballchasing.exceptions import BackoffLimitExceeded, BallchasingFault, DuplicateReplay

from rsc.ballchasing import groups, process
from rsc.ballchasing.ballchasing import BallchasingMixIn, normalize_scores, upload_summary
from rsc.enums import MatchType

FIXTURES = Path(__file__).parent / "fixtures" / "replays"

# Two separate players' recordings of the same online match
SHARED_MATCH_GUID = "4D6EC48011F103E5CE0B728D103E89F4"

GUILD_ID = 1234
TLG = "tlg-root"


# ---------------------------------------------------------------- helpers


def _create_mixin(**attrs) -> BallchasingMixIn:
    """Create a BallchasingMixIn bypassing ABC restrictions and __init__."""
    saved = BallchasingMixIn.__abstractmethods__
    BallchasingMixIn.__abstractmethods__ = frozenset()
    try:
        mixin = object.__new__(BallchasingMixIn)
    finally:
        BallchasingMixIn.__abstractmethods__ = saved

    mixin._ballchasing_api = {}
    mixin._bc_match_locks = {}
    mixin._bc_group_locks = {}
    mixin._bc_group_cache = {}
    mixin._bc_upload_ledger = {}
    for k, v in attrs.items():
        setattr(mixin, k, v)
    return mixin


def _guild(guild_id: int = GUILD_ID) -> MagicMock:
    guild = MagicMock()
    guild.id = guild_id
    guild.name = "Test Guild"
    return guild


def _match(
    *,
    match_id: int = 1,
    day: int | None = 5,
    match_type: str = MatchType.REGULAR,
    home: str = "Bulls",
    away: str = "Sharks",
    tier: str = "Master",
    season: int = 20,
    reported_group: str | None = None,
) -> MagicMock:
    match = MagicMock()
    match.id = match_id
    match.day = day
    match.match_type = match_type
    match.home_team.name = home
    match.home_team.tier = tier
    match.home_team.latest_season = season
    match.away_team.name = away
    match.results = MagicMock(ballchasing_group=reported_group) if reported_group is not None else None
    return match


def _group(group_id: str, name: str) -> MagicMock:
    g = MagicMock()
    g.id = group_id
    g.name = name
    return g


def _api(children: dict[str, list] | None = None) -> MagicMock:
    """A ballchasing Api mock whose get_groups walks a parent -> children map."""
    children = children or {}
    api = MagicMock()

    async def get_groups(group=None, name=None, **kwargs):
        for g in children.get(group, []):
            # Emulate ballchasing's server side name filter as a substring match
            if name is not None and name.casefold() not in g.name.casefold():
                continue
            yield g

    created: list[dict] = []

    async def create_group(name, parent=None, **kwargs):
        result = MagicMock()
        result.id = f"grp-{len(created)}-{name}"
        created.append({"name": name, "parent": parent, "id": result.id})
        children.setdefault(parent, []).append(_group(result.id, name))
        return result

    api.get_groups = get_groups
    api.create_group = AsyncMock(side_effect=create_group)
    api.created = created
    return api


def _parsed(guid: str | None = None, players: list[dict] | None = None, map_code: str = "stadium_p") -> MagicMock:
    parsed = MagicMock()
    properties: dict = {}
    if guid is not None:
        properties["MatchGUID"] = guid
    parsed.header.get_property = properties.get
    parsed.header.properties = properties
    parsed.map_code = map_code
    parsed.player_stats = players or []
    return parsed


def _candidate(
    label: str = "a.replay",
    guid: str | None = SHARED_MATCH_GUID,
    data: bytes = b"replay-bytes",
    players: list[dict] | None = None,
) -> process.ReplayCandidate:
    parsed = _parsed(guid, players if players is not None else DEFAULT_PLAYERS)
    return process.ReplayCandidate(
        label=label,
        data=data,
        parsed=parsed,
        match_guid=guid,
        fingerprint=process.local_fingerprint(parsed),
        digest=md5(data).hexdigest(),
    )


def _bc_player(name: str, score: int, goals: int = 0, assists: int = 0, saves: int = 0, shots: int = 0) -> MagicMock:
    player = MagicMock()
    player.name = name
    player.stats.core.score = score
    player.stats.core.goals = goals
    player.stats.core.assists = assists
    player.stats.core.saves = saves
    player.stats.core.shots = shots
    return player


def _header_player(name: str, team: int, score: int, goals: int = 0, assists: int = 0, saves: int = 0, shots: int = 0) -> dict:
    return {"Name": name, "Team": team, "Score": score, "Goals": goals, "Assists": assists, "Saves": saves, "Shots": shots}


def _bc_replay(
    replay_id: str = "bc1",
    guid: str | None = None,
    status: ballchasing.ReplayStatus | None = ballchasing.ReplayStatus.OK,
    blue: list | None = None,
    orange: list | None = None,
    map_code: str = "stadium_p",
) -> MagicMock:
    replay = MagicMock()
    replay.id = replay_id
    replay.match_guid = guid
    replay.status = status
    replay.map_code = map_code
    replay.blue = MagicMock(players=blue) if blue is not None else None
    replay.orange = MagicMock(players=orange) if orange is not None else None
    return replay


DEFAULT_PLAYERS = [
    _header_player("Alice", 0, 300, goals=1, shots=3),
    _header_player("Bob", 0, 250, saves=2),
    _header_player("Carol", 1, 400, goals=2, shots=5),
    _header_player("Dave", 1, 100, assists=1),
]


def _other_game(shift: int = 0) -> list[dict]:
    """A different game in the same lobby: same players, different box score."""
    return [
        _header_player("Alice", 0, 111 + shift, goals=0, shots=1),
        _header_player("Bob", 0, 222 + shift, saves=1),
        _header_player("Carol", 1, 333 + shift, goals=1, shots=2),
        _header_player("Dave", 1, 444 + shift, assists=0),
    ]


def _matching_bc_replay(
    replay_id: str = "bc1",
    guid: str | None = SHARED_MATCH_GUID,
    status: ballchasing.ReplayStatus | None = ballchasing.ReplayStatus.OK,
) -> MagicMock:
    """A ballchasing replay of the same game `_candidate()` produces."""
    return _bc_replay(
        replay_id,
        guid=guid,
        status=status,
        blue=[_bc_player("Alice", 300, goals=1, shots=3), _bc_player("Bob", 250, saves=2)],
        orange=[_bc_player("Carol", 400, goals=2, shots=5), _bc_player("Dave", 100, assists=1)],
    )


# ---------------------------------------------------------------- group naming


class TestMatchDayName:
    def test_regular_season_is_zero_padded(self):
        assert groups.match_day_name(_match(day=5)) == "Match Day 05"

    def test_postseason_day_zero_is_playoff(self):
        # PostSeasonType.PLAYOFF is 0. `if not match.day` used to reject it.
        assert groups.match_day_name(_match(day=0, match_type=MatchType.POSTSEASON)) == "Playoff"

    def test_postseason_named_rounds(self):
        assert groups.match_day_name(_match(day=4, match_type=MatchType.POSTSEASON)) == "Finals"

    def test_missing_day_raises(self):
        with pytest.raises(ValueError, match="match day"):
            groups.match_day_name(_match(day=None))

    def test_regular_season_day_zero_is_not_an_error(self):
        assert groups.match_day_name(_match(day=0)) == "Match Day 00"


# ---------------------------------------------------------------- group resolution


class TestFindOrCreateGroup:
    async def test_cache_hit_makes_no_api_calls(self):
        api = _api()
        api.get_groups = MagicMock(side_effect=AssertionError("should not list groups"))
        cache = {(TLG, "season 20"): "cached-id"}

        found = await groups.find_or_create_group(api, name="Season 20", parent=TLG, cache=cache)

        assert found == "cached-id"
        api.create_group.assert_not_called()

    async def test_finds_existing_group_ignoring_case(self):
        api = _api({TLG: [_group("existing", "SEASON 20")]})

        found = await groups.find_or_create_group(api, name="Season 20", parent=TLG)

        assert found == "existing"
        api.create_group.assert_not_called()

    async def test_substring_near_miss_does_not_match(self):
        # The server side name filter is a substring match, so a query for
        # "Match Day 05" can return "Match Day 0". Only an exact name counts.
        api = _api({TLG: [_group("wrong", "Match Day 0")]})

        found = await groups.find_or_create_group(api, name="Match Day 05", parent=TLG)

        assert found != "wrong"
        api.create_group.assert_awaited_once()

    async def test_falls_back_to_unfiltered_listing(self):
        """If the name filter misses an existing group, the safety net finds it."""
        existing = _group("existing", "Season 20")
        api = MagicMock()

        async def get_groups(group=None, name=None, **kwargs):
            if name is not None:  # pretend the server filter is broken
                return
            yield existing

        api.get_groups = get_groups
        api.create_group = AsyncMock()

        found = await groups.find_or_create_group(api, name="Season 20", parent=TLG)

        assert found == "existing"
        api.create_group.assert_not_called()

    async def test_creates_and_caches(self):
        api = _api()
        cache: groups.GroupCache = {}

        found = await groups.find_or_create_group(api, name="Season 20", parent=TLG, cache=cache)

        api.create_group.assert_awaited_once()
        assert cache[(TLG, "season 20")] == found


class TestRscMatchBcGroup:
    async def test_reported_match_short_circuits(self):
        api = _api()
        api.get_groups = MagicMock(side_effect=AssertionError("should not list groups"))

        found = await groups.rsc_match_bc_group(api, _guild(), TLG, _match(reported_group="abc123"))

        assert found == "abc123"
        api.create_group.assert_not_called()

    async def test_empty_reported_group_falls_through(self):
        api = _api()

        found = await groups.rsc_match_bc_group(api, _guild(), TLG, _match(reported_group=""))

        assert found != ""
        assert api.create_group.await_count == 5

    async def test_cold_ladder_creates_five_groups_in_order(self):
        api = _api()

        found = await groups.rsc_match_bc_group(api, _guild(), TLG, _match())

        names = [c["name"] for c in api.created]
        assert names == ["Season 20", "Regular Season", "Master", "Match Day 05", "Bulls vs Sharks"]
        # Each level is parented onto the one above it, rooted at the TLG
        expected_parents = [TLG, *[c["id"] for c in api.created[:-1]]]
        assert [c["parent"] for c in api.created] == expected_parents
        assert found == api.created[-1]["id"]

    async def test_warm_cache_creates_nothing(self):
        api = _api()
        cache: groups.GroupCache = {}
        guild = _guild()

        first = await groups.rsc_match_bc_group(api, guild, TLG, _match(), cache=cache)
        api.create_group.reset_mock()
        second = await groups.rsc_match_bc_group(api, guild, TLG, _match(), cache=cache)

        assert first == second
        api.create_group.assert_not_called()


# ---------------------------------------------------------------- locking


class TestMatchGuard:
    async def test_serializes_same_match(self):
        mixin = _create_mixin()
        guild = _guild()
        concurrent = 0
        peak = 0

        async def worker():
            nonlocal concurrent, peak
            async with mixin.bc_match_guard(guild, 1):
                concurrent += 1
                peak = max(peak, concurrent)
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                concurrent -= 1

        await asyncio.gather(*(worker() for _ in range(5)))

        assert peak == 1

    async def test_different_matches_run_concurrently(self):
        mixin = _create_mixin()
        guild = _guild()
        started = asyncio.Event()

        async def first():
            async with mixin.bc_match_guard(guild, 1):
                started.set()
                await asyncio.wait_for(second_done.wait(), timeout=1)

        second_done = asyncio.Event()

        async def second():
            await started.wait()
            async with mixin.bc_match_guard(guild, 2):
                second_done.set()

        await asyncio.gather(first(), second())

        assert second_done.is_set()

    async def test_entry_survives_handoff_to_waiter(self):
        """release() clears `locked` before the waiter runs, so cleanup must refcount."""
        mixin = _create_mixin()
        guild = _guild()
        key = (guild.id, 1)
        holder_entered = asyncio.Event()
        release_holder = asyncio.Event()
        observed: list = []

        async def holder():
            async with mixin.bc_match_guard(guild, 1):
                holder_entered.set()
                await release_holder.wait()

        async def waiter():
            await holder_entered.wait()
            entry_before = mixin._bc_match_locks[key]
            task = asyncio.create_task(_acquire(entry_before))
            await asyncio.sleep(0)  # let the waiter block on the lock
            release_holder.set()
            await task

        async def _acquire(entry_before):
            async with mixin.bc_match_guard(guild, 1):
                # The holder has exited by now. We must be inside the same entry,
                # not a freshly created one.
                observed.append(mixin._bc_match_locks[key] is entry_before)

        await asyncio.gather(holder(), waiter())

        assert observed == [True]
        assert key not in mixin._bc_match_locks

    async def test_entries_are_cleaned_up(self):
        mixin = _create_mixin()
        guild = _guild()

        for i in range(100):
            async with mixin.bc_match_guard(guild, i):
                pass

        assert mixin._bc_match_locks == {}

    async def test_in_progress_probe(self):
        mixin = _create_mixin()
        guild = _guild()

        assert not mixin.bc_match_report_in_progress(guild, 1)
        async with mixin.bc_match_guard(guild, 1):
            assert mixin.bc_match_report_in_progress(guild, 1)
        assert not mixin.bc_match_report_in_progress(guild, 1)


# ---------------------------------------------------------------- match guid


class TestMatchGuid:
    def test_reads_uppercase_key(self):
        assert process.match_guid(_parsed("abc123")) == "ABC123"

    def test_reads_legacy_camelcase_key(self):
        parsed = MagicMock()
        parsed.header.get_property = {"MatchGuid": "abc123"}.get
        assert process.match_guid(parsed) == "ABC123"

    def test_returns_none_when_absent(self):
        assert process.match_guid(_parsed(None)) is None

    def test_returns_none_for_empty_string(self):
        assert process.match_guid(_parsed("")) is None


class TestRealReplayFixtures:
    """Two players' recordings of one match share a GUID but nothing else.

    This is the entire premise of GUID based deduplication. Rocket League
    renamed the header key once already (build 241014), so pin it here.
    """

    def test_same_match_different_recordings(self):
        a = process._parse_bytes((FIXTURES / "same_match_a.replay").read_bytes())
        b = process._parse_bytes((FIXTURES / "same_match_b.replay").read_bytes())

        assert process.match_guid(a) == SHARED_MATCH_GUID
        assert process.match_guid(b) == SHARED_MATCH_GUID
        # Same game, but genuinely different files
        assert a.header.get_property("Id") != b.header.get_property("Id")

    def test_recordings_of_one_game_fingerprint_identically(self):
        """The whole premise of deduplication, against real files.

        These two differ in bytes, replay Id, local timestamp and even the order
        players appear in the header. Only the box score is common to both.
        """
        a = process._parse_bytes((FIXTURES / "same_match_a.replay").read_bytes())
        b = process._parse_bytes((FIXTURES / "same_match_b.replay").read_bytes())

        assert [p["Name"] for p in a.player_stats] != [p["Name"] for p in b.player_stats]
        assert process.local_fingerprint(a) == process.local_fingerprint(b)

    def test_a_different_game_fingerprints_differently(self):
        a = process._parse_bytes((FIXTURES / "same_match_a.replay").read_bytes())
        tampered = process._parse_bytes((FIXTURES / "same_match_b.replay").read_bytes())
        tampered.player_stats[0]["Score"] += 1

        assert process.local_fingerprint(a) != process.local_fingerprint(tampered)

    def test_fixtures_are_byte_distinct(self):
        a = (FIXTURES / "same_match_a.replay").read_bytes()
        b = (FIXTURES / "same_match_b.replay").read_bytes()
        assert md5(a).hexdigest() != md5(b).hexdigest()

    async def test_build_candidates_reads_and_parses(self):
        paths = [str(FIXTURES / "same_match_a.replay"), str(FIXTURES / "same_match_b.replay")]

        candidates = await process.build_candidates(paths)

        assert [c.match_guid for c in candidates] == [SHARED_MATCH_GUID, SHARED_MATCH_GUID]
        assert candidates[0].digest != candidates[1].digest


# ---------------------------------------------------------------- batch validation


class TestDuplicateInBatch:
    def test_no_duplicates(self):
        a = _candidate("a.replay", "GUID-A", b"one")
        b = _candidate("b.replay", "GUID-B", b"two", players=_other_game())
        assert process.duplicate_in_batch([a, b]) is None

    def test_identical_bytes(self):
        a = _candidate("a.replay", "GUID-A", b"same")
        b = _candidate("b.replay", "GUID-B", b"same")
        assert process.duplicate_in_batch([a, b]) is b

    def test_same_game_different_bytes(self):
        """md5 cannot see this: two players' recordings of one game."""
        a = _candidate("a.replay", SHARED_MATCH_GUID, b"recording-a")
        b = _candidate("b.replay", SHARED_MATCH_GUID, b"recording-b")
        assert process.duplicate_in_batch([a, b]) is b

    def test_series_played_in_one_lobby_is_not_a_duplicate(self):
        """Every game in a lobby shares a match GUID.

        Keying this check on the GUID would reject a whole Bo7 submission.
        """
        games = [
            _candidate("g1.replay", SHARED_MATCH_GUID, b"g1"),
            _candidate("g2.replay", SHARED_MATCH_GUID, b"g2", players=_other_game()),
            _candidate("g3.replay", SHARED_MATCH_GUID, b"g3", players=_other_game(shift=7)),
        ]
        assert process.duplicate_in_batch(games) is None

    def test_missing_guids_do_not_collide(self):
        a = _candidate("a.replay", None, b"one")
        b = _candidate("b.replay", None, b"two", players=_other_game())
        assert process.duplicate_in_batch([a, b]) is None


# ---------------------------------------------------------------- stat comparison


# ---------------------------------------------------------------- collision ladder


class TestReplayGroupCollisions:
    async def test_matches_processed_replay_of_same_game(self):
        candidate = _candidate()
        report = await process.replay_group_collisions([candidate], [_matching_bc_replay()])

        assert report.upload == []
        assert report.duplicates == [(candidate, "bc1")]

    async def test_guid_case_is_normalised(self):
        candidate = _candidate()
        existing = _matching_bc_replay(guid=SHARED_MATCH_GUID.lower())

        report = await process.replay_group_collisions([candidate], [existing])

        assert report.duplicates == [(candidate, "bc1")]

    async def test_other_game_in_same_lobby_is_uploaded(self):
        """Same match GUID, different game. Must not be treated as a duplicate."""
        candidate = _candidate(players=_other_game())

        report = await process.replay_group_collisions([candidate], [_matching_bc_replay()])

        assert report.upload == [candidate]
        assert report.duplicates == []

    async def test_pending_replay_cannot_be_compared(self):
        """No stats yet, so nothing to fingerprint. Upload rather than guess."""
        candidate = _candidate()
        pending = _bc_replay("bc1", guid=SHARED_MATCH_GUID, status=ballchasing.ReplayStatus.PENDING)

        report = await process.replay_group_collisions([candidate], [pending])

        assert report.upload == [candidate]

    async def test_failed_replay_never_blocks_a_good_copy(self):
        candidate = _candidate()
        failed = _matching_bc_replay(status=ballchasing.ReplayStatus.FAILED)

        report = await process.replay_group_collisions([candidate], [failed])

        assert report.upload == [candidate]
        assert report.duplicates == []

    async def test_ledger_covers_the_processing_window(self):
        """The core regression: the first reporter's upload is still processing so
        ballchasing exposes neither stats nor a GUID, but we fingerprinted it
        locally at upload time."""
        candidate = _candidate()
        processing = _bc_replay("bc1", guid=None, status=ballchasing.ReplayStatus.PENDING)

        report = await process.replay_group_collisions(
            [candidate],
            [processing],
            ledger={candidate.fingerprint: "bc1"},
        )

        assert report.upload == []
        assert report.duplicates == [(candidate, "bc1")]

    async def test_ledger_does_not_block_a_different_game(self):
        candidate = _candidate(players=_other_game())
        stale = _candidate()

        report = await process.replay_group_collisions([candidate], [], ledger={stale.fingerprint: "bc1"})

        assert report.upload == [candidate]

    async def test_new_game_is_uploaded(self):
        candidate = _candidate(guid="GUID-NEW", players=_other_game(shift=3))

        report = await process.replay_group_collisions([candidate], [_matching_bc_replay()])

        assert report.upload == [candidate]

    async def test_one_bc_replay_absorbs_only_one_candidate(self):
        a = _candidate("a.replay", SHARED_MATCH_GUID, b"one")
        b = _candidate("b.replay", SHARED_MATCH_GUID, b"two")

        report = await process.replay_group_collisions([a, b], [_matching_bc_replay()])

        assert report.duplicates == [(a, "bc1")]
        assert report.upload == [b]

    async def test_candidate_without_player_data_is_uploaded(self):
        candidate = _candidate(players=[])

        report = await process.replay_group_collisions([candidate], [_matching_bc_replay()])

        assert candidate.fingerprint is None
        assert report.upload == [candidate]

    async def test_full_series_against_a_partially_filled_group(self):
        """Three games from one lobby, the first already uploaded."""
        games = [
            _candidate("g1.replay", SHARED_MATCH_GUID, b"g1"),
            _candidate("g2.replay", SHARED_MATCH_GUID, b"g2", players=_other_game()),
            _candidate("g3.replay", SHARED_MATCH_GUID, b"g3", players=_other_game(shift=7)),
        ]

        report = await process.replay_group_collisions(games, [_matching_bc_replay()])

        assert report.duplicates == [(games[0], "bc1")]
        assert report.upload == [games[1], games[2]]


class TestFingerprint:
    def test_agrees_across_player_ordering(self):
        forwards = _parsed(SHARED_MATCH_GUID, DEFAULT_PLAYERS)
        backwards = _parsed(SHARED_MATCH_GUID, list(reversed(DEFAULT_PLAYERS)))

        assert process.local_fingerprint(forwards) == process.local_fingerprint(backwards)

    def test_ignores_the_match_guid(self):
        """A series in one lobby shares a GUID, so it cannot be part of identity."""
        with_guid = _parsed(SHARED_MATCH_GUID, DEFAULT_PLAYERS)
        without = _parsed(None, DEFAULT_PLAYERS)

        assert process.local_fingerprint(with_guid) == process.local_fingerprint(without)

    def test_differs_when_the_box_score_differs(self):
        a = _parsed(SHARED_MATCH_GUID, DEFAULT_PLAYERS)
        b = _parsed(SHARED_MATCH_GUID, _other_game())

        assert process.local_fingerprint(a) != process.local_fingerprint(b)

    def test_none_without_player_data(self):
        assert process.local_fingerprint(_parsed(SHARED_MATCH_GUID, [])) is None

    def test_local_and_ballchasing_agree(self):
        """Ballchasing reports stats as floats, replay headers as ints."""
        local = process.local_fingerprint(_parsed(SHARED_MATCH_GUID, DEFAULT_PLAYERS))

        assert process.bc_fingerprint(_matching_bc_replay()) == local

    def test_ballchasing_float_stats_normalise(self):
        local = process.local_fingerprint(_parsed(SHARED_MATCH_GUID, DEFAULT_PLAYERS))
        floaty = _bc_replay(
            guid=SHARED_MATCH_GUID,
            blue=[_bc_player("Alice", 300.0, goals=1.0, shots=3.0), _bc_player("Bob", 250.0, saves=2.0)],
            orange=[_bc_player("Carol", 400.0, goals=2.0, shots=5.0), _bc_player("Dave", 100.0, assists=1.0)],
        )

        assert process.bc_fingerprint(floaty) == local

    def test_ballchasing_none_while_pending(self):
        assert process.bc_fingerprint(_matching_bc_replay(status=ballchasing.ReplayStatus.PENDING)) is None

    def test_ballchasing_none_without_stats(self):
        blue = [MagicMock(name="Alice", stats=None)]
        orange = [MagicMock(name="Carol", stats=None)]

        assert process.bc_fingerprint(_bc_replay(blue=blue, orange=orange)) is None

    def test_ballchasing_none_with_one_empty_team(self):
        assert process.bc_fingerprint(_bc_replay(blue=[], orange=[])) is None

    def test_null_platform_does_not_raise(self):
        """The parser emits Platform=None for one ByteProperty encoding."""
        players = [dict(p, Platform=None) for p in DEFAULT_PLAYERS]

        assert process.local_fingerprint(_parsed(SHARED_MATCH_GUID, players)) is not None

    def test_unknown_team_value_does_not_raise(self):
        players = [dict(p, Team=2) for p in DEFAULT_PLAYERS]

        assert process.local_fingerprint(_parsed(SHARED_MATCH_GUID, players)) is not None

    def test_roster_size_mismatch_differs(self):
        full = process.local_fingerprint(_parsed(SHARED_MATCH_GUID, DEFAULT_PLAYERS))
        short = process.local_fingerprint(_parsed(SHARED_MATCH_GUID, DEFAULT_PLAYERS[:3]))

        assert full != short

    def test_player_without_a_name_is_unusable(self):
        players = [dict(p, Name=None) for p in DEFAULT_PLAYERS]

        assert process.local_fingerprint(_parsed(SHARED_MATCH_GUID, players)) is None


# ---------------------------------------------------------------- ledger


class TestLedger:
    def test_round_trip(self):
        mixin = _create_mixin()
        guild = _guild()

        mixin._ledger_record(guild, "grp", SHARED_MATCH_GUID, "bc1")

        assert mixin._ledger_read(guild, "grp") == {SHARED_MATCH_GUID: "bc1"}

    def test_expired_entries_are_pruned(self):
        mixin = _create_mixin()
        guild = _guild()
        mixin._ledger_record(guild, "grp", SHARED_MATCH_GUID, "bc1")

        # Age the entry past the TTL
        bucket = mixin._bc_upload_ledger[(guild.id, "grp")]
        replay_id, ts = bucket[SHARED_MATCH_GUID]
        bucket[SHARED_MATCH_GUID] = (replay_id, ts - 7200)

        assert mixin._ledger_read(guild, "grp") == {}
        assert (guild.id, "grp") not in mixin._bc_upload_ledger

    def test_groups_are_isolated(self):
        mixin = _create_mixin()
        guild = _guild()
        mixin._ledger_record(guild, "grp-a", SHARED_MATCH_GUID, "bc1")

        assert mixin._ledger_read(guild, "grp-b") == {}

    def test_guilds_are_isolated(self):
        mixin = _create_mixin()
        mixin._ledger_record(_guild(1), "grp", SHARED_MATCH_GUID, "bc1")

        assert mixin._ledger_read(_guild(2), "grp") == {}


# ---------------------------------------------------------------- scores


class TestNormalizeScores:
    def test_correct_orientation_is_unchanged(self):
        assert normalize_scores("Bulls", 3, 1, _match()) == (3, 1)

    def test_swapped_orientation_is_corrected(self):
        # Reporter typed the away team into the home field
        assert normalize_scores("Sharks", 3, 1, _match()) == (1, 3)

    def test_unrecognised_name_is_left_alone(self):
        assert normalize_scores("Wolves", 3, 1, _match()) == (3, 1)

    def test_matching_is_case_and_whitespace_insensitive(self):
        assert normalize_scores("  sharks ", 3, 1, _match()) == (1, 3)


# ---------------------------------------------------------------- upload


class TestUploadReplays:
    def _mixin(self, api):
        mixin = _create_mixin()
        mixin._ballchasing_api = {GUILD_ID: api}
        return mixin

    async def test_mixed_batch(self):
        api = MagicMock()
        api.patch_replay = AsyncMock()
        api.upload_replay_from_bytes = AsyncMock(
            side_effect=[
                MagicMock(id="bc-ok"),
                DuplicateReplay({"id": "bc-dupe"}),
                BallchasingFault("boom"),
            ]
        )
        mixin = self._mixin(api)
        candidates = [
            _candidate("a.replay", "GUID-A", b"a"),
            _candidate("b.replay", "GUID-B", b"b"),
            _candidate("c.replay", "GUID-C", b"c"),
        ]

        result = await mixin.upload_replays(_guild(), group="grp", candidates=candidates)

        assert (result.uploaded, result.skipped, result.failed) == (1, 1, 1)
        api.patch_replay.assert_awaited_once_with("bc-dupe", group="grp")

    async def test_backoff_fails_the_rest_of_the_batch(self):
        api = MagicMock()
        api.patch_replay = AsyncMock()
        api.upload_replay_from_bytes = AsyncMock(
            side_effect=[MagicMock(id="bc-ok"), BackoffLimitExceeded("slow down"), MagicMock(id="never")]
        )
        mixin = self._mixin(api)
        candidates = [_candidate(f"{i}.replay", f"GUID-{i}", bytes([i])) for i in range(4)]

        result = await mixin.upload_replays(_guild(), group="grp", candidates=candidates)

        assert api.upload_replay_from_bytes.await_count == 2
        assert result.uploaded == 1
        assert result.failed == 3

    async def test_ledger_written_for_upload_and_patch(self):
        api = MagicMock()
        api.patch_replay = AsyncMock()
        api.upload_replay_from_bytes = AsyncMock(side_effect=[MagicMock(id="bc-ok"), DuplicateReplay({"id": "bc-dupe"})])
        mixin = self._mixin(api)
        guild = _guild()
        candidates = [_candidate("a.replay", data=b"a"), _candidate("b.replay", data=b"b", players=_other_game())]

        await mixin.upload_replays(guild, group="grp", candidates=candidates)

        assert mixin._ledger_read(guild, "grp") == {
            candidates[0].fingerprint: "bc-ok",
            candidates[1].fingerprint: "bc-dupe",
        }

    async def test_replay_without_player_data_is_not_recorded(self):
        api = MagicMock()
        api.upload_replay_from_bytes = AsyncMock(return_value=MagicMock(id="bc-ok"))
        mixin = self._mixin(api)
        guild = _guild()

        await mixin.upload_replays(guild, group="grp", candidates=[_candidate("a.replay", players=[])])

        assert mixin._ledger_read(guild, "grp") == {}

    async def test_uploads_the_candidate_bytes(self):
        api = MagicMock()
        api.upload_replay_from_bytes = AsyncMock(return_value=MagicMock(id="bc-ok"))
        mixin = self._mixin(api)
        payload = b"the-actual-replay"

        await mixin.upload_replays(_guild(), group="grp", candidates=[_candidate("a.replay", "GUID-A", payload)])

        assert api.upload_replay_from_bytes.await_args.kwargs["replay_data"] is payload

    async def test_failed_patch_is_reported(self):
        api = MagicMock()
        api.patch_replay = AsyncMock(side_effect=RuntimeError("nope"))
        api.upload_replay_from_bytes = AsyncMock(side_effect=DuplicateReplay({"id": "bc-dupe"}))
        mixin = self._mixin(api)

        result = await mixin.upload_replays(_guild(), group="grp", candidates=[_candidate()])

        assert result.failed == 1


class TestUploadSummary:
    def test_uploads_only(self):
        result = process.ReplayUploadResult(group="grp", outcomes=[process.UploadOutcome(_candidate(), replay_id="x")])
        assert upload_summary(result) == "Uploaded **1**"

    def test_all_three_counts(self):
        result = process.ReplayUploadResult(
            group="grp",
            outcomes=[
                process.UploadOutcome(_candidate(), replay_id="x"),
                process.UploadOutcome(_candidate(), replay_id="y", duplicate=True),
                process.UploadOutcome(_candidate(), error="boom"),
            ],
        )
        assert upload_summary(result) == "Uploaded **1** · skipped **1** duplicate(s) · failed **1**"


# ---------------------------------------------------------------- candidates


class TestBuildCandidates:
    async def test_attachment_is_read_once(self):
        attachment = MagicMock(spec=discord.Attachment)
        attachment.filename ="a.replay"
        attachment.read = AsyncMock(return_value=b"bytes")

        with patch.object(process, "_parse_bytes", return_value=_parsed("GUID-A")):
            candidates = await process.build_candidates([attachment])

        attachment.read.assert_awaited_once()
        assert candidates[0].data == b"bytes"
        assert candidates[0].label == "a.replay"

    async def test_parsing_is_offloaded_to_a_thread(self):
        attachment = MagicMock(spec=discord.Attachment)
        attachment.filename ="a.replay"
        attachment.read = AsyncMock(return_value=b"bytes")

        with patch.object(process.asyncio, "to_thread", AsyncMock(return_value=_parsed("GUID-A"))) as to_thread:
            await process.build_candidates([attachment])

        to_thread.assert_awaited_once()

    async def test_unparseable_file_names_itself(self):
        attachment = MagicMock(spec=discord.Attachment)
        attachment.filename ="broken.replay"
        attachment.read = AsyncMock(return_value=b"not a replay")

        with pytest.raises(process.ReplayParseError, match="broken.replay"):
            await process.build_candidates([attachment])


# ---------------------------------------------------------------- api lifecycle


class TestPrepareBallchasing:
    async def test_unchanged_token_reuses_the_session(self):
        existing = MagicMock(auth_key="token")
        existing.close = AsyncMock()
        mixin = _create_mixin(_get_bc_auth_token=AsyncMock(return_value="token"))
        mixin._ballchasing_api = {GUILD_ID: existing}

        with patch.object(ballchasing.Api, "create", AsyncMock()) as create:
            await mixin.prepare_ballchasing(_guild())

        create.assert_not_awaited()
        existing.close.assert_not_awaited()
        assert mixin._ballchasing_api[GUILD_ID] is existing

    async def test_changed_token_swaps_and_closes(self):
        existing = MagicMock(auth_key="old")
        existing.close = AsyncMock()
        fresh = MagicMock(auth_key="new")
        mixin = _create_mixin(_get_bc_auth_token=AsyncMock(return_value="new"))
        mixin._ballchasing_api = {GUILD_ID: existing}
        mixin._bc_group_cache = {GUILD_ID: {("a", "b"): "c"}}

        with patch.object(ballchasing.Api, "create", AsyncMock(return_value=fresh)):
            await mixin.prepare_ballchasing(_guild())

        assert mixin._ballchasing_api[GUILD_ID] is fresh
        existing.close.assert_awaited_once()
        assert GUILD_ID not in mixin._bc_group_cache

    async def test_no_token_is_a_noop(self):
        mixin = _create_mixin(_get_bc_auth_token=AsyncMock(return_value=None))

        with patch.object(ballchasing.Api, "create", AsyncMock()) as create:
            await mixin.prepare_ballchasing(_guild())

        create.assert_not_awaited()
        assert mixin._ballchasing_api == {}


# ---------------------------------------------------------------- end to end


class TestProcessMatchReplays:
    def _mixin(self, api):
        mixin = _create_mixin(_get_top_level_group=AsyncMock(return_value=TLG))
        mixin._ballchasing_api = {GUILD_ID: api}
        return mixin

    def _replay_api(self, existing: list | None = None):
        api = _api()
        api.patch_replay = AsyncMock()
        api.upload_replay_from_bytes = AsyncMock(side_effect=lambda **kw: MagicMock(id=f"bc-{kw['replay_data'].decode()}"))

        group_contents = list(existing or [])

        async def get_group_replays(group_id, deep=False, recurse=False):
            for r in group_contents:
                yield r

        api.get_group_replays = get_group_replays
        api.group_contents = group_contents
        return api

    async def test_second_reporter_skips_everything(self):
        """Two teammates report the same match back to back. The second upload
        must be a no-op even though ballchasing is still processing the first."""
        api = self._replay_api()
        mixin = self._mixin(api)
        guild = _guild()
        match = _match()

        first = await mixin.process_match_replays(guild, match, [_candidate("a.replay", "GUID-A", b"a")])

        # First reporter's replay is now in the group but still processing, so
        # ballchasing reports no match_guid and no stats for it.
        api.group_contents.append(_bc_replay("bc-a", guid=None, status=ballchasing.ReplayStatus.PENDING))
        api.upload_replay_from_bytes.reset_mock()

        second = await mixin.process_match_replays(guild, match, [_candidate("b.replay", "GUID-A", b"b")])

        assert first.group == second.group
        assert second.uploaded == 0
        assert second.skipped == 1
        api.upload_replay_from_bytes.assert_not_called()

    async def test_group_ladder_is_only_built_once(self):
        api = self._replay_api()
        mixin = self._mixin(api)
        guild = _guild()

        await mixin.process_match_replays(guild, _match(match_id=1), [_candidate("a.replay", "GUID-A", b"a")])
        created_after_first = api.create_group.await_count

        # A different match on the same day reuses season/type/tier/match-day
        await mixin.process_match_replays(guild, _match(match_id=2, home="Bulls", away="Wolves"), [_candidate("b.replay", "GUID-B", b"b")])

        assert created_after_first == 5
        assert api.create_group.await_count == 6  # only the new match group

    async def test_concurrent_reports_of_different_matches_share_one_ladder(self):
        api = self._replay_api()
        mixin = self._mixin(api)
        guild = _guild()

        await asyncio.gather(
            mixin.process_match_replays(guild, _match(match_id=1, away="Sharks"), [_candidate("a.replay", "GUID-A", b"a")]),
            mixin.process_match_replays(guild, _match(match_id=2, away="Wolves"), [_candidate("b.replay", "GUID-B", b"b")]),
        )

        names = [c["name"] for c in api.created]
        # One season, type, tier and match day between them; two match groups
        assert names.count("Season 20") == 1
        assert names.count("Match Day 05") == 1
        assert names.count("Bulls vs Sharks") == 1
        assert names.count("Bulls vs Wolves") == 1

    async def test_reported_match_reuses_stored_group(self):
        api = self._replay_api()
        mixin = self._mixin(api)

        result = await mixin.process_match_replays(
            _guild(), _match(reported_group="stored-group"), [_candidate("a.replay", "GUID-A", b"a")]
        )

        assert result.group == "stored-group"
        api.create_group.assert_not_called()
