import unittest

from app.knowledge.chunking import chunk_text


class ChunkTextTests(unittest.TestCase):
    def test_empty_text_produces_no_chunks(self) -> None:
        self.assertEqual(chunk_text(""), [])

    def test_short_text_produces_one_chunk(self) -> None:
        text = "hello world this is a short faq answer"
        chunks = chunk_text(text, chunk_size_words=300, overlap_words=50)
        self.assertEqual(chunks, [text])

    def test_long_text_splits_into_multiple_overlapping_chunks(self) -> None:
        words = [f"word{i}" for i in range(1000)]
        text = " ".join(words)
        chunks = chunk_text(text, chunk_size_words=300, overlap_words=50)
        self.assertGreater(len(chunks), 1)
        # last word of one chunk's overlap should reappear at the start of the next
        first_chunk_words = chunks[0].split()
        second_chunk_words = chunks[1].split()
        self.assertEqual(first_chunk_words[-50:], second_chunk_words[:50])

    def test_all_words_are_covered(self) -> None:
        words = [f"word{i}" for i in range(1000)]
        text = " ".join(words)
        chunks = chunk_text(text, chunk_size_words=300, overlap_words=50)
        self.assertTrue(chunks[-1].split()[-1] == words[-1])

    def test_rejects_overlap_not_smaller_than_chunk_size(self) -> None:
        with self.assertRaises(ValueError):
            chunk_text("some text", chunk_size_words=100, overlap_words=100)


if __name__ == "__main__":
    unittest.main()
