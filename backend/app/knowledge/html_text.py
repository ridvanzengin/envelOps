"""Strips a fetched HTML page down to plain text for chunking — the
REQUIREMENTS.md §5 "otherwise chunked as text" fallback path. Stdlib only
(`html.parser`), no new dependency. Does not parse schema.org FAQPage
structured Q&A pairs (§5's "parsed as clean Q&A pairs where available") —
deliberately deferred, not attempted here.
"""

from html.parser import HTMLParser

_SKIPPED_TAGS = frozenset({"script", "style"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self.fragments: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIPPED_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIPPED_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        stripped = data.strip()
        if stripped:
            self.fragments.append(stripped)


def extract_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return "\n".join(parser.fragments)
