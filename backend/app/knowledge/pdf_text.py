"""PDF -> plain text extraction (docs/ARCHITECTURE.md §6 -- the one
documented, deliberately deferred knowledge-source type: the model's
`type` column already anticipated "pdf", ingesting one just needed a
real PDF-parsing library). Mirrors html_text.py's own shape (one
extract_text(...) function, no class), but takes raw bytes instead of a
string since a PDF is a binary upload, not fetched/decoded text.
"""

from io import BytesIO

from pypdf import PdfReader


def extract_text(data: bytes) -> str:
    """Raises ValueError on anything that isn't a readable, unencrypted
    PDF -- the caller (app/knowledge/api.py) turns that into a 400, same
    shape as web_fetch.py's httpx.HTTPError -> 400 for a bad url. pypdf's
    own failure modes for malformed input aren't limited to one specific
    exception type, so this catches broadly at the boundary rather than
    trying to enumerate them."""
    try:
        reader = PdfReader(BytesIO(data))
        if reader.is_encrypted:
            raise ValueError("PDF is encrypted/password-protected")
        pages_text = [page.extract_text() or "" for page in reader.pages]
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"not a valid PDF: {exc}") from exc

    return "\n\n".join(pages_text)
