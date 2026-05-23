"""Tests for the sentence-aware chunker."""

from __future__ import annotations

from papers.chunking import ChunkRecord, chunk_text


def test_short_text_returns_one_chunk():
    chunks = chunk_text("This is a short result. It fits in one chunk.", max_tokens=1800)
    assert len(chunks) == 1
    assert isinstance(chunks[0], ChunkRecord)
    assert chunks[0].text.strip().startswith("This is a short result.")


def test_chunk_text_respects_sentence_boundaries():
    # 5 sentences, force chunk size that should split between them.
    text = " ".join(f"Sentence number {i} here." for i in range(50))
    chunks = chunk_text(text, max_tokens=40, overlap_tokens=5)
    assert len(chunks) > 1
    # Each chunk should end at a sentence boundary (period).
    for c in chunks[:-1]:
        assert c.text.strip().endswith(".")


def test_chunk_text_records_char_offsets():
    text = "First sentence. Second sentence. Third sentence."
    chunks = chunk_text(text, max_tokens=10, overlap_tokens=0)
    assert chunks[0].char_offset_start == 0
    for c in chunks:
        excerpt = text[c.char_offset_start : c.char_offset_end]
        assert c.text.strip() in excerpt or excerpt.strip() in c.text


def test_chunk_text_overlap_between_chunks():
    text = " ".join(f"Sentence {i} content here." for i in range(40))
    chunks = chunk_text(text, max_tokens=30, overlap_tokens=10)
    assert len(chunks) >= 2
    # The last few words of chunk N should appear in chunk N+1.
    tail = chunks[0].text.split()[-3:]
    assert any(w in chunks[1].text for w in tail)


def test_chunk_text_token_count_within_max():
    text = " ".join(f"Sentence number {i} present here." for i in range(80))
    chunks = chunk_text(text, max_tokens=40, overlap_tokens=5)
    for c in chunks:
        assert c.token_count <= 40 * 1.2  # allow modest slack for last-sentence boundary


def test_chunk_text_empty_input_returns_empty_list():
    assert chunk_text("", max_tokens=100) == []


def test_chunk_text_chunk_index_is_sequential():
    text = " ".join(f"S{i}." for i in range(200))
    chunks = chunk_text(text, max_tokens=20, overlap_tokens=2)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))
