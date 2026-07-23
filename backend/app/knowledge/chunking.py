"""Splits source text into overlapping chunks for embedding (docs/
REQUIREMENTS.md §5: "~300-500 tokens, overlap"). This counts words, not
tokens — no tokenizer library is installed yet, and word count is only a
rough proxy for token count (roughly 0.75 words per token for English).
The default is set conservatively low to account for that; swap in a real
tokenizer-based count before trusting this near the target range.
"""


def chunk_text(
    text: str, *, chunk_size_words: int = 300, overlap_words: int = 50
) -> list[str]:
    if overlap_words >= chunk_size_words:
        raise ValueError("overlap_words must be smaller than chunk_size_words")

    words = text.split()
    if not words:
        return []

    step = chunk_size_words - overlap_words
    chunks = []
    start = 0
    while start < len(words):
        chunks.append(" ".join(words[start : start + chunk_size_words]))
        if start + chunk_size_words >= len(words):
            break
        start += step
    return chunks
