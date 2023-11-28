from rscapi.exceptions import ApiException as RscApiException


class RscException(Exception):
    """Base exception type for RSC Bot"""

    def __init__(self, *args, **kwargs):
        self.response = kwargs.pop("response", None)
        if self.response is not None and isinstance(self.response, RscApiException):
            self.status = self.response.status
            self.reason = self.response.body
        super().__init__(*args, **kwargs)


# Transactions


class TransactionException(RscException):
    """Generic Transaction Exception Base Type"""


class PastTransactionsEndDate(TransactionException):
    """Attempt to cut a player past the transactions end date"""
