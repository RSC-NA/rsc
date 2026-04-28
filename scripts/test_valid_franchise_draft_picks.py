#!/usr/bin/env python3

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table
from rscapi import ApiClient, Configuration, DraftPicksApi, FranchisesApi

API_KEY = os.environ.get("RSC_API_KEY")
API_HOST = "https://staging-api.rscna.com/api/v1"
LOG_LEVEL = os.environ.get("RSC_DRAFT_LOG_LEVEL", "INFO").upper()
LEAGUE_ID = 1
PAGE_SIZE = 50

console = Console()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(message)s",
    datefmt="[%X]",
    handlers=[
        RichHandler(
            console=console,
            rich_tracebacks=True,
            markup=True,
            show_path=False,
        )
    ],
)
logger = logging.getLogger("rsc.scripts.test_valid_franchise_draft_picks")

if not API_KEY:
    logger.error("RSC API key not found in environment variable RSC_API_KEY")
    sys.exit(1)

CONF = Configuration(
    host=API_HOST,
    api_key={"Api-Key": API_KEY},
    api_key_prefix={"Api-Key": "Api-Key"},
)


def _tier_key(value: str) -> str:
    return value.strip().casefold()


def _pick_tier_name(pick: Any) -> str | None:
    season_tier = getattr(pick, "tier", None)
    tier = getattr(season_tier, "tier", None)
    name = getattr(tier, "name", None)
    if isinstance(name, str):
        return name
    return None


def _round_number(pick: Any) -> int | None:
    round_no = getattr(pick, "round", None)
    if isinstance(round_no, int):
        return round_no
    return None


def _satisfies_round_rule(rounds: list[int], target_round: int) -> bool:
    """Return True when a single tier satisfies the rule for target_round.

    Rules map as:
    - 1st round: must contain at least one round 1 pick
    - Nth round (N >= 2): must contain a round N pick OR at least N picks in rounds <= N
    """
    if target_round == 1:
        return 1 in rounds

    has_exact_round = target_round in rounds
    better_or_equal_count = sum(1 for round_no in rounds if round_no <= target_round)
    return has_exact_round or better_or_equal_count >= target_round


def _summarize_rounds(rounds: list[int], *, max_items: int = 12) -> str:
    ordered = sorted(rounds)
    if len(ordered) <= max_items:
        return str(ordered)
    return f"{ordered[:max_items]}... (+{len(ordered) - max_items} more)"


def _describe_round_rule_failure(tier_name: str, rounds: list[int], target_round: int) -> str:
    if target_round == 1:
        return (
            f"{tier_name}: missing a round 1 pick; "
            f"rounds present={_summarize_rounds(rounds)}"
        )

    exact_count = sum(1 for round_no in rounds if round_no == target_round)
    better_or_equal_count = sum(1 for round_no in rounds if round_no <= target_round)
    return (
        f"{tier_name}: round {target_round} picks={exact_count}, "
        f"picks <= {target_round}={better_or_equal_count} (needs >= {target_round} picks"
        f"rounds present={_summarize_rounds(rounds)}"
    )


def _validate_round_coverage_rule(
    rule_label: str,
    target_round: int,
    allowed_missing_tiers: int,
    tiers: list[str],
    rounds_by_tier: dict[str, list[int]],
) -> str | None:
    total_tiers = len(tiers)
    required_tiers = max(total_tiers - allowed_missing_tiers, 0)

    passing_tiers = [
        tier_name
        for tier_name in tiers
        if _satisfies_round_rule(rounds_by_tier[tier_name], target_round)
    ]
    failing_tiers = [tier_name for tier_name in tiers if tier_name not in passing_tiers]

    if len(passing_tiers) >= required_tiers:
        return None

    failure_reasons = [
        _describe_round_rule_failure(tier_name, rounds_by_tier[tier_name], target_round)
        for tier_name in failing_tiers
    ]

    return (
        f"Rule {rule_label}: passes in {len(passing_tiers)}/{total_tiers} tiers "
        f"(requires at least {required_tiers}). "
        f"Failing tiers: {', '.join(failing_tiers)}. "
        f"Why: {' | '.join(failure_reasons)}"
    )


def _validate_rule_5_2_5_1(tiers: list[str], rounds_by_tier: dict[str, list[int]]) -> str | None:
    return _validate_round_coverage_rule(
        rule_label="5.2.5.1",
        target_round=1,
        allowed_missing_tiers=1,
        tiers=tiers,
        rounds_by_tier=rounds_by_tier,
    )


def _validate_rule_5_2_5_2(tiers: list[str], rounds_by_tier: dict[str, list[int]]) -> str | None:
    return _validate_round_coverage_rule(
        rule_label="5.2.5.2",
        target_round=2,
        allowed_missing_tiers=1,
        tiers=tiers,
        rounds_by_tier=rounds_by_tier,
    )


def _validate_rule_5_2_5_3(tiers: list[str], rounds_by_tier: dict[str, list[int]]) -> str | None:
    return _validate_round_coverage_rule(
        rule_label="5.2.5.3",
        target_round=3,
        allowed_missing_tiers=2,
        tiers=tiers,
        rounds_by_tier=rounds_by_tier,
    )


def _validate_rule_5_2_5_4(tiers: list[str], rounds_by_tier: dict[str, list[int]]) -> str | None:
    return _validate_round_coverage_rule(
        rule_label="5.2.5.4",
        target_round=4,
        allowed_missing_tiers=2,
        tiers=tiers,
        rounds_by_tier=rounds_by_tier,
    )


def _validate_rule_5_2_5_5(tiers: list[str], rounds_by_tier: dict[str, list[int]]) -> str | None:
    return _validate_round_coverage_rule(
        rule_label="5.2.5.5",
        target_round=5,
        allowed_missing_tiers=2,
        tiers=tiers,
        rounds_by_tier=rounds_by_tier,
    )


def _validate_rule_5_2_5_6(tiers: list[str], rounds_by_tier: dict[str, list[int]]) -> str | None:
    retain_failures = [
        tier_name
        for tier_name in tiers
        if sum(1 for round_no in rounds_by_tier[tier_name] if round_no <= 5) < 3
    ]
    if not retain_failures:
        return None

    failure_reasons = [
        (
            f"{tier_name}: picks in rounds 1-5="
            f"{sum(1 for round_no in rounds_by_tier[tier_name] if round_no <= 5)} (needs >= 3); "
            f"rounds present={_summarize_rounds(rounds_by_tier[tier_name])}"
        )
        for tier_name in retain_failures
    ]

    return (
        "Rule 5.2.5.6: must retain at least three of first five picks in each tier. "
        f"Failing tiers: {', '.join(retain_failures)}. "
        f"Why: {' | '.join(failure_reasons)}"
    )


def _split_violation_message(violation: str) -> tuple[str, str]:
    if violation.startswith("Rule "):
        rule_part, _, reason = violation.partition(":")
        return rule_part.replace("Rule ", "", 1).strip(), reason.strip()
    return "Unknown", violation


def _render_validation_tables(season_number: int, results: list[dict[str, Any]]) -> None:
    total = len(results)
    failed = sum(1 for result in results if result["violations"])
    passed = total - failed

    summary = Table(title=f"Franchise Draft Pick Validation - Season {season_number}")
    summary.add_column("Franchise", style="cyan")
    summary.add_column("Tiers", justify="right")
    summary.add_column("Picks", justify="right")
    summary.add_column("Status", justify="center")
    summary.add_column("Failed Rules", overflow="fold")

    for result in results:
        failed_rules = ", ".join(result["failed_rules"]) if result["failed_rules"] else "-"
        status = "[green]VALID[/green]" if not result["violations"] else "[red]INVALID[/red]"
        summary.add_row(
            result["franchise"],
            str(result["tier_count"]),
            str(result["pick_count"]),
            status,
            failed_rules,
        )

    console.print(summary)
    console.print(f"Summary: [green]{passed} valid[/green], [red]{failed} invalid[/red], total={total}")

    invalid_results = [result for result in results if result["violations"]]
    if not invalid_results:
        return

    details = Table(title="Validation Failures", show_lines=True)
    details.add_column("Franchise", style="cyan")
    details.add_column("Rule", style="magenta")
    details.add_column("Why", overflow="fold")

    for result in invalid_results:
        for violation in result["violations"]:
            rule_id, reason = _split_violation_message(violation)
            details.add_row(result["franchise"], rule_id, reason)

    console.print(details)


def validate_franchise_pick_layout(franchise: str, tiers: list[str], picks: list[Any]) -> list[str]:
    tier_name_map = {_tier_key(tier_name): tier_name for tier_name in tiers}
    rounds_by_tier: dict[str, list[int]] = {tier_name: [] for tier_name in tiers}

    for pick in picks:
        tier_name = _pick_tier_name(pick)
        round_no = _round_number(pick)
        if not tier_name or round_no is None:
            continue

        key = _tier_key(tier_name)
        mapped_tier_name = tier_name_map.get(key)
        if mapped_tier_name is None:
            continue
        rounds_by_tier[mapped_tier_name].append(round_no)

    validations = [
        _validate_rule_5_2_5_1(tiers, rounds_by_tier),
        _validate_rule_5_2_5_2(tiers, rounds_by_tier),
        _validate_rule_5_2_5_3(tiers, rounds_by_tier),
        _validate_rule_5_2_5_4(tiers, rounds_by_tier),
        _validate_rule_5_2_5_5(tiers, rounds_by_tier),
        _validate_rule_5_2_5_6(tiers, rounds_by_tier),
    ]
    violations = [violation for violation in validations if violation]

    logger.debug("Round distribution for %s: %s", franchise, rounds_by_tier)
    return violations


async def fetch_franchise_tier_map(franchises_api: FranchisesApi) -> dict[str, set[str]]:
    franchises = await franchises_api.franchises_list(league=LEAGUE_ID)
    franchise_tiers: dict[str, set[str]] = {}

    for franchise in franchises:
        franchise_name = getattr(franchise, "name", None)
        if not isinstance(franchise_name, str):
            continue

        tiers = getattr(franchise, "tiers", None) or []
        tier_names = {
            tier_name
            for tier in tiers
            for tier_name in [getattr(tier, "name", None)]
            if isinstance(tier_name, str)
        }

        if tier_names:
            franchise_tiers[franchise_name] = tier_names

    return franchise_tiers


async def fetch_franchise_draft_picks(
    draft_picks_api: DraftPicksApi,
    season_number: int,
    franchise: str,
) -> list[Any]:
    all_picks: list[Any] = []
    offset = 0

    while True:
        logger.debug("Fetching draft picks for franchise '%s' season %s with offset %s", franchise, season_number, offset)
        response = await draft_picks_api.draft_picks_list(
            franchise=franchise,
            season_number=season_number,
            deleted=False,
            limit=PAGE_SIZE,
            offset=offset,
        )

        results = list(response.results or [])
        all_picks.extend(results)

        if not results:
            break

        if len(all_picks) >= response.count:
            break

        offset += PAGE_SIZE

    return all_picks


async def validate_season(season_number: int, franchise_name: str | None) -> int:
    async with ApiClient(CONF) as client:
        franchises_api = FranchisesApi(client)
        draft_picks_api = DraftPicksApi(client)

        franchise_tiers = await fetch_franchise_tier_map(franchises_api)
        logger.info("Fetched %d franchises from Franchises API", len(franchise_tiers))
        if not franchise_tiers:
            logger.error("No franchises found from Franchises API")
            return 1

        if franchise_name:
            logger.info("Filtering to franchise '%s' using case-insensitive match", franchise_name)
            selected_franchises = [
                name for name in franchise_tiers if _tier_key(name) == _tier_key(franchise_name)
            ]
            if not selected_franchises:
                logger.error("Franchise '%s' not found in season %s", franchise_name, season_number)
                return 1
        else:
            selected_franchises = sorted(franchise_tiers)

        logger.info("Validating %s franchise(s) for season %s", len(selected_franchises), season_number)

        failed_franchises = 0
        franchise_results: list[dict[str, Any]] = []
        for franchise in selected_franchises:
            logger.info("Validating franchise '%s' with tiers: %s", franchise, ", ".join(sorted(franchise_tiers[franchise])))
            tiers = sorted(franchise_tiers[franchise])
            picks = await fetch_franchise_draft_picks(
                draft_picks_api=draft_picks_api,
                season_number=season_number,
                franchise=franchise,
            )

            logger.debug("[%s] Loaded %s picks across %s tiers", franchise, len(picks), len(tiers))

            violations = validate_franchise_pick_layout(
                franchise=franchise,
                tiers=tiers,
                picks=picks,
            )

            failed_rules = [
                _split_violation_message(violation)[0]
                for violation in violations
            ]

            franchise_results.append(
                {
                    "franchise": franchise,
                    "tier_count": len(tiers),
                    "pick_count": len(picks),
                    "violations": violations,
                    "failed_rules": failed_rules,
                }
            )

            if violations:
                failed_franchises += 1
                logger.warning("[%s] INVALID (%s rule violation(s))", franchise, len(violations))
            else:
                logger.info("[%s] VALID", franchise)

        _render_validation_tables(season_number=season_number, results=franchise_results)

        if failed_franchises:
            logger.error(
                "Validation failed for %s of %s franchise(s)",
                failed_franchises,
                len(selected_franchises),
            )
            return 1

        logger.info("All franchise draft pick layouts are valid for season %s", season_number)
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate franchise draft pick legality for a season using RSCAPI DraftPicks."
    )
    parser.add_argument(
        "season",
        type=int,
        help="Season number to validate",
    )
    parser.add_argument(
        "-f",
        "--franchise",
        type=str,
        default=None,
        help="Optional franchise name to validate a single franchise",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(validate_season(args.season, args.franchise))
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
