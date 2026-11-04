import itertools
import logging
import time
import traceback
from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CapturedException:
    id: int
    created: float
    logger: str
    message: str
    traceback: str

    @property
    def summary(self) -> str:
        """The exception line at the bottom of the traceback, e.g. `KeyError: 'x'`."""
        return next((line for line in reversed(self.traceback.splitlines()) if line.strip()), "")


class ExceptionRecorder(logging.Handler):
    """Keep the most recent log records that carry an exception, from any logger."""

    def __init__(self, maxlen: int = 25):
        super().__init__()
        self.started = time.time()
        self._ids = itertools.count(1)
        self._entries: deque[CapturedException] = deque(maxlen=maxlen)

    def emit(self, record: logging.LogRecord) -> None:
        if not record.exc_info or record.exc_info[1] is None:
            return
        try:
            entry = CapturedException(
                id=next(self._ids),
                created=record.created,
                logger=record.name,
                message=record.getMessage(),
                traceback="".join(traceback.format_exception(record.exc_info[1])),
            )
        except Exception:
            self.handleError(record)
            return
        self._entries.append(entry)

    def entries(self) -> list[CapturedException]:
        """Stored exceptions, newest first."""
        # Records also arrive from worker threads (asyncio.to_thread), and
        # Handler.handle() holds this lock around emit().
        self.acquire()
        try:
            return list(reversed(self._entries))
        finally:
            self.release()

    def get(self, entry_id: int) -> CapturedException | None:
        self.acquire()
        try:
            return next((e for e in self._entries if e.id == entry_id), None)
        finally:
            self.release()
