"""Sentence-boundary-aware token chunker.

Splits a long text into chunks of ≤ ``max_tokens`` tokens, never cutting
mid-sentence. Adjacent chunks overlap by ``overlap_tokens`` to preserve
context for the extractor.

Token counting uses tiktoken's cl100k_base encoding. NLTK's
``punkt_tab`` sentence tokenizer provides the sentence boundaries; the
pre-trained English model (with learned abbreviations) is loaded once and
cached so biomedical abbreviations like "e.g.", "Fig.", "vs." do not cause
spurious sentence splits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import nltk
import tiktoken


@dataclass
class ChunkRecord:
    chunk_index: int
    text: str
    token_count: int
    char_offset_start: int
    char_offset_end: int


_ENCODER = tiktoken.get_encoding("cl100k_base")
_NLTK_READY = False
_TOKENIZER: Any = None


def _ensure_nltk() -> None:
    global _NLTK_READY, _TOKENIZER
    if _NLTK_READY:
        return
    try:
        nltk.data.find("tokenizers/punkt_tab")
    except LookupError:
        nltk.download("punkt_tab", quiet=True)
    # Load the pre-trained English punkt_tab tokenizer so its learned
    # abbreviations (e.g., "e.g.", "Fig.", "vs.") are in effect.
    _TOKENIZER = nltk.data.load("tokenizers/punkt_tab/english.pickle")
    _NLTK_READY = True


def _count_tokens(s: str) -> int:
    return len(_ENCODER.encode(s))


def _sentences_with_offsets(text: str) -> list[tuple[str, int, int]]:
    """Return list of (sentence_text, char_start, char_end)."""
    _ensure_nltk()
    assert _TOKENIZER is not None
    spans = list(_TOKENIZER.span_tokenize(text))
    return [(text[start:end], start, end) for start, end in spans]


def chunk_text(
    text: str,
    *,
    max_tokens: int = 1800,
    overlap_tokens: int = 200,
) -> list[ChunkRecord]:
    """Greedy pack sentences into chunks of ≤ max_tokens.

    Sentences exceeding max_tokens are emitted on their own (last-resort
    overflow) — never split mid-sentence even if oversized.
    """
    if not text.strip():
        return []

    sentences = _sentences_with_offsets(text)
    if not sentences:
        return []

    chunks: list[ChunkRecord] = []
    chunk_index = 0
    i = 0
    n = len(sentences)
    while i < n:
        buffer: list[tuple[str, int, int]] = []
        token_total = 0
        j = i
        while j < n:
            sent_text, start, end = sentences[j]
            sent_tokens = _count_tokens(sent_text)
            if token_total + sent_tokens > max_tokens and buffer:
                break
            buffer.append((sent_text, start, end))
            token_total += sent_tokens
            j += 1
        if not buffer:
            # Single sentence longer than max_tokens — emit anyway.
            sent_text, start, end = sentences[i]
            buffer = [(sent_text, start, end)]
            token_total = _count_tokens(sent_text)
            j = i + 1

        chunk_str = " ".join(s for s, _, _ in buffer).strip()
        start_offset = buffer[0][1]
        end_offset = buffer[-1][2]
        chunks.append(
            ChunkRecord(
                chunk_index=chunk_index,
                text=chunk_str,
                token_count=token_total,
                char_offset_start=start_offset,
                char_offset_end=end_offset,
            )
        )
        chunk_index += 1

        if j >= n:
            break

        # Walk back from j until overlap_tokens of context is captured.
        if overlap_tokens <= 0:
            i = j
            continue
        overlap_total = 0
        k = j - 1
        while k > i and overlap_total < overlap_tokens:
            overlap_total += _count_tokens(sentences[k][0])
            k -= 1
        i = max(k + 1, i + 1)

    return chunks
