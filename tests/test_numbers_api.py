import pytest
from rscapi import NumbersApi

pytestmark = pytest.mark.integration


class TestNumbersApiContract:
    """Verify all expected rscapi NumbersApi methods exist without calling them."""

    EXPECTED_METHODS = ("numbers_mmr_list",)

    @pytest.mark.parametrize("method_name", EXPECTED_METHODS)
    def test_method_exists(self, method_name: str):
        """Ensure NumbersApi has the expected method."""
        assert hasattr(NumbersApi, method_name), f"NumbersApi missing expected method: {method_name}"
        assert callable(getattr(NumbersApi, method_name)), f"NumbersApi.{method_name} is not callable"
