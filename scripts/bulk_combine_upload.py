#!/usr/bin/env python3

import argparse
import asyncio
import os
import sys
import time
from collections import Counter
from pathlib import Path

import ballchasing
from ballchasing.exceptions import BallchasingException, BallchasingFault, DuplicateReplay
from dotenv import load_dotenv

UPLOADED = "uploaded"
SKIPPED = "skipped"
MOVED = "moved"
FAILED = "failed"

# Uploads leave at this rate until ballchasing objects. Deliberately well under
# the tier's general calls/second: see UploadPacer.
DEFAULT_UPLOAD_RATE = 4.0
# How many uploads may be in flight at once. Requests that leave evenly spaced
# still arrive clustered when many are in flight and latency varies, and it is
# arrival time that ballchasing counts.
DEFAULT_CONCURRENCY = 10
# Multiplier applied to the gap between uploads each time we are rate limited.
BACKOFF_FACTOR = 1.5
# Never crawl below this, no matter how many 429s come back.
FLOOR_RATE = 0.5
# Seconds to let one slowdown take effect before considering another. Dozens of
# in-flight uploads observe the same 429s, and reacting to each would drop
# straight to the floor after a single burst.
SETTLE_SECONDS = 3.0


class UploadPacer:
    """Adaptive pacing for the upload endpoint.

    Ballchasing documents calls/second per tier for listing, fetching and
    patching replays, but publishes no limit for POST /v2/upload, and the
    library applies the general tier rate to every endpoint alike. Uploads do
    not tolerate that rate, so this starts lower and gives ground whenever
    ballchasing answers with a 429, settling on a rate the account accepts.
    """

    def __init__(self, rate: float, floor: float = FLOOR_RATE) -> None:
        self._interval = 1 / rate
        self._floor_interval = 1 / floor
        self._lock = asyncio.Lock()
        self._next = 0.0
        self._seen_rate_limits = 0
        self._last_change = 0.0

    @property
    def rate(self) -> float:
        return 1 / self._interval

    async def wait(self) -> None:
        """Block until this caller's turn to send."""
        async with self._lock:
            now = asyncio.get_running_loop().time()
            send_at = max(now, self._next)
            self._next = send_at + self._interval
            delay = send_at - now
        # Slept outside the lock so waiting callers keep their reserved slots
        # rather than serialising behind each other's sleeps.
        if delay > 0:
            await asyncio.sleep(delay)

    def observe(self, rate_limit_count: int) -> None:
        """React to 429s the library absorbed while retrying."""
        if rate_limit_count <= self._seen_rate_limits:
            return

        self._seen_rate_limits = rate_limit_count
        now = asyncio.get_running_loop().time()
        if now - self._last_change < SETTLE_SECONDS:
            return

        slower = min(self._interval * BACKOFF_FACTOR, self._floor_interval)
        if slower <= self._interval:
            return

        self._interval = slower
        self._last_change = now
        print(f"Rate limited, slowing uploads to {self.rate:.1f}/s")


async def find_group(bapi: ballchasing.Api, name: str, parent: str) -> str | None:
    """Return the id of the child group named `name` under `parent`, if it exists."""
    target = name.casefold()

    # Narrow the listing server side first. The name filter's matching semantics
    # are not documented, so the comparison below is what actually decides.
    async for g in bapi.get_groups(group=parent, name=name):
        if g.name.casefold() == target:
            return g.id

    # The filter may be exact and case sensitive. Pay for one unfiltered listing
    # before reporting the group as missing.
    async for g in bapi.get_groups(group=parent):
        if g.name.casefold() == target:
            return g.id

    return None


async def create_group(bapi: ballchasing.Api, name: str, parent: str) -> str:
    result = await bapi.create_group(
        name=name,
        parent=parent,
        player_identification=ballchasing.PlayerIdentificationBy.ID,
        team_identification=ballchasing.TeamIdentificationBy.CLUSTERS,
    )
    return result.id


async def group_replay_ids(bapi: ballchasing.Api, group: str) -> set[str]:
    """Replay ids already in the group, so a re-run can tell a duplicate apart.

    Ballchasing answers a duplicate upload with the existing replay's id but
    not its group, and the Replay model does not carry group membership, so
    this listing is what makes "already where we want it" answerable.
    """
    return {r.id async for r in bapi.get_group_replays(group_id=group)}


async def handle_duplicate(
    bapi: ballchasing.Api, replay: Path, group: str, existing: set[str], exc: DuplicateReplay
) -> str:
    """Ballchasing already has these exact bytes. Make sure they land in our group."""
    if not exc.id:
        print(f"Duplicate, but ballchasing did not say which replay: {replay.name}")
        return FAILED

    if exc.id in existing:
        print(f"Already in group, skipped: {replay.name}")
        return SKIPPED

    # The duplicate lives outside this group (or in no group at all), so move
    # it in. Without this, a resumed run would skip replays that never made it
    # into the group and quietly leave the day incomplete.
    try:
        await bapi.patch_replay(exc.id, group=group)
    except BallchasingException as patch_exc:
        print(f"Could not move existing replay into group: {replay.name} ({patch_exc})")
        return FAILED

    print(f"Moved existing replay into group: {replay.name}")
    return MOVED


async def upload_replay(
    bapi: ballchasing.Api,
    replay: Path,
    group: str,
    existing: set[str],
    gate: asyncio.Semaphore,
    pacer: UploadPacer,
) -> str:
    """Upload one replay, waiting for the pacer's go-ahead first."""
    async with gate:
        await pacer.wait()
        try:
            await bapi.upload_replay(replay_file=str(replay.absolute()), group=group)
            print(f"Uploaded: {replay.name}")
            return UPLOADED
        except DuplicateReplay as exc:
            return await handle_duplicate(bapi, replay, group, existing, exc)
        except BallchasingFault:
            print(f"Ballchasing parser error: {replay.name}")
            return FAILED
        except BallchasingException as exc:
            print(f"Failed: {replay.name} ({exc})")
            return FAILED
        finally:
            # The library swallows 429s by retrying, so its counter is the only
            # place they surface. Checked even on failure paths, since a 429
            # storm is exactly when we most need to back off.
            pacer.observe(bapi.rate_limit_count)


async def upload_all(
    bapi: ballchasing.Api,
    files: list[Path],
    group: str,
    existing: set[str],
    concurrency: int,
    pacer: UploadPacer,
) -> Counter[str]:
    """Upload the folder through a sliding window of `concurrency` uploads.

    A sliding window rather than discrete batches of N: both cap how many
    uploads are in flight, but a batch cannot start until the slowest member of
    the previous one finishes, which idles the other slots for no benefit. Rate
    is the pacer's job; this only bounds concurrency.
    """
    gate = asyncio.Semaphore(concurrency)

    # gather() rather than a TaskGroup: one replay blowing up should not cancel
    # the rest of the folder. Whatever fails is reported and can be picked up by
    # re-running, which is the whole point of the duplicate handling above.
    results = await asyncio.gather(
        *(upload_replay(bapi, r, group, existing, gate, pacer) for r in files),
        return_exceptions=True,
    )

    counts: Counter[str] = Counter()
    for replay, result in zip(files, results, strict=True):
        if isinstance(result, BaseException):
            print(f"Unexpected error: {replay.name} ({result!r})")
            counts[FAILED] += 1
        else:
            counts[result] += 1
    return counts


if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    parser = argparse.ArgumentParser(
        description="Bulk upload combine replays to a ballchasing group for a match day."
    )
    parser.add_argument("parent", type=str, help="Top level ballchasing group")
    parser.add_argument("day", type=int, help="Combine match day number")
    parser.add_argument("directory", type=str, help="Replay directory")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually create the group and upload. Without it, only report what would happen.",
    )
    parser.add_argument(
        "--rate",
        type=float,
        default=DEFAULT_UPLOAD_RATE,
        help=(
            "Uploads per second to start at. Ballchasing publishes no limit for "
            "the upload endpoint, so this backs off automatically on a 429 and "
            f"reports where it settled. (Default: {DEFAULT_UPLOAD_RATE})"
        ),
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=DEFAULT_CONCURRENCY,
        help=f"Maximum uploads in flight at once. (Default: {DEFAULT_CONCURRENCY})",
    )
    argv = parser.parse_args()

    parent: str = argv.parent
    day: int = argv.day
    execute: bool = argv.execute
    rate: float = argv.rate
    concurrency: int = argv.concurrency

    if rate <= 0:
        print(f"--rate must be greater than 0: {rate}")
        sys.exit(1)

    if concurrency < 1:
        print(f"--concurrency must be at least 1: {concurrency}")
        sys.exit(1)

    load_dotenv()
    bckey = os.environ.get("BALLCHASING_KEY")
    if not bckey:
        print("Unable to find Ballchasing API key (BALLCHASING_KEY)")
        sys.exit(1)

    replays = Path(argv.directory)

    if not (replays.exists() and replays.is_dir()):
        print(f"Invalid directory: {replays}")
        sys.exit(1)

    # The library's own limiter stays at the tier default. It governs the group
    # listing and patch calls, which are covered by the documented tier rate;
    # uploads are paced by UploadPacer on top of it.
    bapi = ballchasing.Api(
        auth_key=bckey,
        patreon_type=ballchasing.PatreonType.ORG,
        print_on_rate_limit=True,
    )
    pacer = UploadPacer(rate)

    files = sorted(replays.glob(pattern="*.replay"))
    group_name = f"Combine Day {day}"

    try:
        # ping() reports the account's real patreon tier and retunes the
        # limiter, so the upload rate comes from ballchasing rather than the
        # tier assumed above. It also fails fast on a bad key.
        ping = loop.run_until_complete(bapi.ping())
        print(f"Authenticated as {ping.name} ({bapi.patreon_type} tier)")

        # The lookup is read only, so a dry run still reports whether the group
        # already exists instead of guessing.
        group = loop.run_until_complete(find_group(bapi, name=group_name, parent=parent))
        existing: set[str] = set()
        if group:
            existing = loop.run_until_complete(group_replay_ids(bapi, group))

        if not execute:
            print("DRY RUN (pass --execute to apply)")
            if group:
                print(f"Group '{group_name}' already exists under {parent}: {group}")
                print(f"It already holds {len(existing)} replay(s); duplicates of those are skipped")
            else:
                print(f"Would create group '{group_name}' under {parent}")
            print(f"Would upload {len(files)} replay(s) from {replays} to that group")
            print(f"Starting rate: {rate:.1f} upload(s)/s, up to {concurrency} in flight")
            for r in files:
                print(f"  {r.name}")
            sys.exit(0)

        if group:
            print(f"Found existing group '{group_name}': {group} ({len(existing)} replay(s) already in it)")
        else:
            group = loop.run_until_complete(create_group(bapi, name=group_name, parent=parent))
            print(f"Created group '{group_name}': {group}")

        print(f"Uploading {len(files)} replay(s) at {rate:.1f}/s, up to {concurrency} in flight")
        start = time.monotonic()
        counts = loop.run_until_complete(upload_all(bapi, files, group, existing, concurrency, pacer))
        elapsed = time.monotonic() - start

        print(
            f"Finished {len(files)} replay(s) in {elapsed:.1f}s "
            f"({counts[UPLOADED]} uploaded, {counts[SKIPPED]} already in group, "
            f"{counts[MOVED]} moved in, {counts[FAILED]} failed)"
        )
        if bapi.rate_limit_count:
            print(
                f"Rate limited {bapi.rate_limit_count} time(s); settled at {pacer.rate:.1f}/s. "
                f"Start there next time with --rate {pacer.rate:.1f}"
            )
        if counts[FAILED]:
            print("Re-run the same command to retry the failures; anything already uploaded is skipped.")
            sys.exit(1)
    finally:
        loop.run_until_complete(bapi.close())
        loop.close()
