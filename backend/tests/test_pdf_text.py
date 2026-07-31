from unittest.mock import MagicMock, patch

import pytest

from app.knowledge.pdf_text import extract_text


class TestExtractText:
    def test_joins_page_text_with_blank_line(self) -> None:
        page1 = MagicMock()
        page1.extract_text.return_value = "Page one."
        page2 = MagicMock()
        page2.extract_text.return_value = "Page two."
        reader = MagicMock()
        reader.is_encrypted = False
        reader.pages = [page1, page2]
        with patch("app.knowledge.pdf_text.PdfReader", return_value=reader):
            assert extract_text(b"fake pdf bytes") == "Page one.\n\nPage two."

    def test_treats_a_page_with_no_extractable_text_as_empty(self) -> None:
        # pypdf's own extract_text() can return None for an image-only or
        # otherwise text-less page -- must not crash "\n\n".join on it.
        page = MagicMock()
        page.extract_text.return_value = None
        reader = MagicMock()
        reader.is_encrypted = False
        reader.pages = [page]
        with patch("app.knowledge.pdf_text.PdfReader", return_value=reader):
            assert extract_text(b"fake pdf bytes") == ""

    def test_rejects_encrypted_pdf(self) -> None:
        reader = MagicMock()
        reader.is_encrypted = True
        with patch("app.knowledge.pdf_text.PdfReader", return_value=reader):
            with pytest.raises(ValueError, match="encrypted"):
                extract_text(b"fake pdf bytes")

    def test_wraps_a_parse_failure_as_value_error(self) -> None:
        # pypdf's own failure modes for malformed input aren't limited to
        # one specific exception type -- confirms the broad except in
        # extract_text actually normalizes whatever it throws.
        with patch(
            "app.knowledge.pdf_text.PdfReader", side_effect=Exception("corrupt stream")
        ):
            with pytest.raises(ValueError, match="not a valid PDF"):
                extract_text(b"garbage")
