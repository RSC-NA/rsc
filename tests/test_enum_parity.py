import sys
from pathlib import Path

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.enums import EventAction, EventCategory, EventSeverity, StaffPositions, TransactionType
from rscapi.models.action_enum import ActionEnum
from rscapi.models.category_enum import CategoryEnum
from rscapi.models.position_enum import PositionEnum
from rscapi.models.severity_enum import SeverityEnum
from rscapi.models.transaction_response_type_enum import TransactionResponseTypeEnum


def test_transaction_type_covers_api_enum():
    """Every transaction type the API can return must be representable locally.

    Drift here caused a ValueError crash in `/transactions history` when the API
    started returning `INT` (Intent to Play).
    """
    api_values = {e.value for e in TransactionResponseTypeEnum}
    local_values = {e.value for e in TransactionType}
    missing = api_values - local_values
    assert not missing, f"TransactionType is missing API values: {sorted(missing)}"


def test_staff_positions_covers_api_enum():
    """Every elevated role position the API can return must be representable locally.

    `StaffPositions` gates access to privileged commands (see `rsc.checks`), so a
    missing value silently locks out whoever holds that position.
    """
    api_values = {e.value for e in PositionEnum}
    local_values = {e.value for e in StaffPositions}
    missing = api_values - local_values
    assert not missing, f"StaffPositions is missing API values: {sorted(missing)}"


def test_event_category_covers_api_enum():
    """Every league event category the API can emit must be representable locally.

    `CategoryEnum` has only three values and is the likeliest of the event enums
    to gain more. The poller degrades unknown values to a generic embed rather
    than crashing, but a missing value means events render without a real label.
    """
    api_values = {e.value for e in CategoryEnum}
    local_values = {e.value for e in EventCategory}
    missing = api_values - local_values
    assert not missing, f"EventCategory is missing API values: {sorted(missing)}"


def test_event_action_covers_api_enum():
    """Every league event action the API can emit must be representable locally.

    Drift here is what motivated the lenient parsing fallback in
    `rsc.events.events.fetch_league_events`: a single unrecognized value fails
    pydantic validation for the *entire* list response, not one element.
    """
    api_values = {e.value for e in ActionEnum}
    local_values = {e.value for e in EventAction}
    missing = api_values - local_values
    assert not missing, f"EventAction is missing API values: {sorted(missing)}"


def test_event_severity_covers_api_enum():
    """Every league event severity the API can emit must be representable locally.

    Severity drives the embed colour, so a missing value silently renders an
    errored system event as if it were routine.
    """
    api_values = {e.value for e in SeverityEnum}
    local_values = {e.value for e in EventSeverity}
    missing = api_values - local_values
    assert not missing, f"EventSeverity is missing API values: {sorted(missing)}"


def test_event_severity_rank_covers_every_member():
    """`rank` hard codes the ordering, so a new member must be slotted into it."""
    ranks = sorted(s.rank for s in EventSeverity)
    assert ranks == list(range(len(EventSeverity)))
