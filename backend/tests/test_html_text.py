import unittest

from app.knowledge.html_text import extract_text


class ExtractTextTests(unittest.TestCase):
    def test_strips_tags_and_keeps_text(self) -> None:
        html = "<html><body><h1>Shipping</h1><p>We ship worldwide.</p></body></html>"
        self.assertEqual(extract_text(html), "Shipping\nWe ship worldwide.")

    def test_skips_script_and_style_content(self) -> None:
        html = (
            "<html><head><style>body { color: red; }</style></head>"
            "<body><script>alert('hi')</script><p>Real content.</p></body></html>"
        )
        self.assertEqual(extract_text(html), "Real content.")

    def test_empty_html_produces_empty_text(self) -> None:
        self.assertEqual(extract_text("<html><body></body></html>"), "")

    def test_collapses_whitespace_only_fragments(self) -> None:
        html = "<p>  \n  </p><p>Kept.</p>"
        self.assertEqual(extract_text(html), "Kept.")


if __name__ == "__main__":
    unittest.main()
