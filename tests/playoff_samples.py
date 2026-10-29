"""Sample playoff hunts shaped like the API's, for the /playoffs tests.

Elite: conferences and divisions, two groups of 8 with 4 spots each (2 division winners + 2 wildcards).
Master: the whole tier, one group of 14 with 8 spots. Every team has 4 games left, so max wins = wins + 4.
"""

import zlib

from rscapi.models.tier_playoff_hunt import TierPlayoffHunt

DIVISIONS = {"M": "Mountain", "O": "Ocean", "E": "Ember", "C": "Cloud"}


def team(
    rank: int,
    name: str,
    won: int,
    lost: int,
    *,
    reason: str | None = None,
    delta: str = "",
    magic: int | None = None,
    division: str = "N",
    remaining: int = 4,
    seed: int | None = None,
    draw: str | None = None,
) -> dict:
    return {
        "team_id": zlib.crc32(name.encode()),
        "team_name": name,
        "franchise_id": rank,
        "franchise_name": f"{name} Franchise",
        "franchise_prefix": name[:3].upper(),
        "franchise_logo_url": "",
        "conference": "L",
        "conference_label": "Lunar",
        "division": division,
        "division_label": DIVISIONS.get(division, "None"),
        "overall_rank": rank,
        "overall_games_back": 0.0,
        "playoff_rank": rank,
        "playoff_seed": seed if seed is not None else (rank if reason else None),
        "playoff_group_label": "Lunar",
        "playoff_cutoff": 4,
        "playoff_qualified": bool(reason),
        "playoff_qualifier_reason": reason,
        "tiebreak_draw": draw,
        "playoff_status_label": "In Cut" if reason else "Outside",
        "playoff_delta_label": delta,
        "playoff_magic_number": magic,
        "playoff_magic_number_label": "-" if magic is None else str(magic),
        "remaining_games": remaining,
        "max_possible_games_won": won + remaining,
        "group_games_back": None,
        "group_games_won": won,
        "group_games_lost": lost,
        "group_win_pct": 50.0,
        "games_played": won + lost,
        "games_won": won,
        "games_lost": lost,
        "win_pct": round(won / (won + lost) * 100, 1) if won + lost else 0.0,
        "goals": 50,
        "opponent_goals": 40,
        "goal_differential": 10,
        "shots": 200,
        "shot_pct": 25.0,
    }


def group(label: str, cutoff: int, teams: list[dict], *, divisions: tuple[str, ...] = (), cutline_rank: int | None = None) -> dict:
    return {
        "label": label,
        "conference": label[0],
        "accent": label.lower(),
        "cutoff": cutoff,
        "cutline_rank": cutoff if cutline_rank is None else cutline_rank,
        "divisions": [{"division": code, "label": DIVISIONS[code]} for code in divisions],
        "teams": teams,
    }


def hunt(groups: list[dict], *, fmt: str = "DIV", tier: str = "Elite", complete: bool = False) -> TierPlayoffHunt:
    labels = {"DIV": "Conferences & divisions", "CONF": "Conferences", "TIER": "Whole tier"}
    return TierPlayoffHunt.model_validate(
        {
            "tier_id": 7,
            "tier_name": tier,
            "tier_position": 5,
            "playoff_format": fmt,
            "playoff_format_label": labels[fmt],
            "playoff_format_source": "configured",
            "regular_season_complete": complete,
            "groups": groups,
        }
    )


def lunar() -> dict:
    return group(
        "Lunar",
        4,
        [
            team(1, "Quantum", 15, 3, reason="division", delta="Leads Mountain", magic=0, division="M"),
            team(2, "Voltage", 13, 5, reason="division", delta="Leads Ocean", magic=2, division="O"),
            team(3, "Kestrel", 12, 6, reason="wildcard", delta="Wildcard", magic=3, division="M"),
            team(4, "Orbit", 10, 8, reason="wildcard", delta="Wildcard", magic=4, division="O"),
            team(5, "Hydra", 10, 8, delta="Tiebreaker", division="M"),
            team(6, "Wandering Nomads", 8, 10, delta="2 wins back", division="O"),
            team(7, "Glacier", 4, 14, delta="6 wins back", division="M"),
            team(8, "Lantern", 3, 15, delta="7 wins back", division="O"),
        ],
        divisions=("M", "O"),
    )


def solar() -> dict:
    return group(
        "Solar",
        4,
        [
            team(1, "Phoenix", 15, 3, reason="division", delta="Leads Ember", magic=0, division="E"),
            team(2, "Tempest", 14, 4, reason="division", delta="Division winner", magic=0, division="C"),
            team(3, "Cinder", 12, 6, reason="wildcard", delta="Wildcard", magic=2, division="E"),
            team(4, "Aurora", 11, 7, reason="wildcard", delta="Wildcard", magic=3, division="C"),
            team(5, "Monsoon", 9, 9, delta="2 wins back", division="E"),
            team(6, "Zephyr", 7, 11, delta="4 wins back", division="C"),
            team(7, "Ashfall", 4, 14, delta="7 wins back", division="E"),
            team(8, "Drizzle", 3, 15, delta="8 wins back", division="C"),
        ],
        divisions=("C", "E"),
    )


def master_group() -> dict:
    rows = [
        ("Pulsar", 16, 2, 0),
        ("Sentinels", 14, 4, 0),
        ("Comets", 13, 5, 0),
        ("Raptors", 12, 6, 1),
        ("Wolfpack", 11, 7, 2),
        ("Mavericks", 11, 7, 2),
        ("Titans", 10, 8, 3),
        ("Spartans", 9, 9, 4),
    ]
    teams = [team(i, name, w, lost, reason="cut", delta="Top 8", magic=m) for i, (name, w, lost, m) in enumerate(rows, start=1)]
    chasers = [
        ("Vipers", 8, 10),
        ("Cyclones", 7, 11),
        ("Monarchs", 6, 12),
        ("Neon Desert Outlaws", 5, 13),
        ("Bandits", 3, 15),
        ("Rogues", 2, 16),
    ]
    for i, (name, w, lost) in enumerate(chasers, start=9):
        back = 9 - w
        teams.append(team(i, name, w, lost, delta=f"{back} win{'s' if back != 1 else ''} back"))
    return group("Master", 8, teams)


def elite_hunt(*, complete: bool = False) -> TierPlayoffHunt:
    return hunt([lunar(), solar()], fmt="DIV", tier="Elite", complete=complete)


def master_hunt(*, complete: bool = False) -> TierPlayoffHunt:
    return hunt([master_group()], fmt="TIER", tier="Master", complete=complete)


def large_hunt() -> TierPlayoffHunt:
    """Two conferences of 10 with long names, a worst case for the message limits."""
    groups = []
    for label in ("Lunar", "Solar"):
        teams = []
        for rank in range(1, 11):
            name = f"{label} Extraordinarily Long Team Name {rank}"
            reason = "division" if rank <= 2 else "wildcard" if rank <= 6 else None
            delta = "Leads Mountain" if rank <= 2 else "Wildcard" if rank <= 6 else f"{rank - 6} wins back"
            teams.append(
                team(
                    rank,
                    name,
                    20 - rank,
                    rank,
                    reason=reason,
                    delta=delta,
                    magic=rank if reason else None,
                    division="M" if rank % 2 else "O",
                )
            )
        groups.append(group(label, 6, teams, divisions=("M", "O")))
    return hunt(groups, fmt="DIV", tier="Premier")
