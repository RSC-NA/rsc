import math
from collections.abc import Iterator, Sequence

from rsc.utils import utils


class Pagify(Iterator[str]):
    """Generate multiple pages from the given text.

    The returned iterator supports length estimation with :func:`operator.length_hint()`.

    Note
    ----
    This does not respect code blocks or inline code.

    Parameters
    ----------
    text : str
        The content to pagify and send.
    delims : `sequence` of `str`, optional
        Characters where page breaks will occur. If no delimiters are found
        in a page, the page will break after ``page_length`` characters.
        By default this only contains the newline.

    Other Parameters
    ----------------
    priority : `bool`
        Set to :code:`True` to choose the page break delimiter based on the
        order of ``delims``. Otherwise, the page will always break at the
        last possible delimiter.
    escape_mass_mentions : `bool`
        If :code:`True`, any mass mentions (here or everyone) will be
        silenced.
    shorten_by : `int`
        How much to shorten each page by. Defaults to 8.
    page_length : `int`
        The maximum length of each page. Defaults to 2000.

    Yields
    ------
    `str`
        Pages of the given text.

    """

    # when changing signature of this method, please update it in docs/framework_utils.rst as well
    def __init__(
        self,
        text: str,
        delims: Sequence[str] = ("\n",),
        *,
        priority: bool = False,
        escape_mass_mentions: bool = True,
        shorten_by: int = 8,
        page_length: int = 2000,
    ) -> None:
        self._text = text
        self._delims = delims
        self._priority = priority
        self._escape_mass_mentions = escape_mass_mentions
        self._shorten_by = shorten_by
        self._page_length = page_length - shorten_by

        self._start = 0
        self._end = len(text)

    def __repr__(self) -> str:
        text = self._text
        if len(text) > 20:
            text = f"{text[:19]}\N{HORIZONTAL ELLIPSIS}"
        return (
            "pagify("
            f"{text!r},"
            f" {self._delims!r},"
            f" priority={self._priority!r},"
            f" escape_mass_mentions={self._escape_mass_mentions!r},"
            f" shorten_by={self._shorten_by!r},"
            f" page_length={self._page_length + self._shorten_by!r}"
            ")"
        )

    def __length_hint__(self) -> int:
        return math.ceil((self._end - self._start) / self._page_length)

    def __iter__(self) -> "Pagify":
        return self

    def __next__(self) -> str:
        text = self._text
        escape_mass_mentions = self._escape_mass_mentions
        page_length = self._page_length
        start = self._start
        end = self._end

        while (end - start) > page_length:
            stop = start + page_length
            if escape_mass_mentions:
                stop -= text.count("@here", start, stop) + text.count("@everyone", start, stop)
            closest_delim_it = (text.rfind(d, start + 1, stop) for d in self._delims)
            if self._priority:  # noqa: SIM108
                closest_delim = next((x for x in closest_delim_it if x > 0), -1)
            else:
                closest_delim = max(closest_delim_it)
            stop = closest_delim if closest_delim != -1 else stop
            if escape_mass_mentions:  # noqa: SIM108
                to_send = utils.escape(text[start:stop], mass_mentions=True)
            else:
                to_send = text[start:stop]
            start = self._start = stop
            if len(to_send.strip()) > 0:
                return to_send

        if len(text[start:end].strip()) > 0:
            self._start = end
            if escape_mass_mentions:
                return utils.escape(text[start:end], mass_mentions=True)
            else:
                return text[start:end]

        raise StopIteration
