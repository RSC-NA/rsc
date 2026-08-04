import sys
from pathlib import Path

# Add the project root to the path so we can import the modules
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from rsc.enums import TransactionType
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
