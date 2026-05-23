"""Tests for extract.routing — model→queue map."""

from __future__ import annotations

import pytest

from extract.prompts import SUPPORTED_OLLAMA_MODELS
from extract.routing import MODEL_TO_QUEUE, queue_for_model


def test_every_model_has_a_queue():
    for model in SUPPORTED_OLLAMA_MODELS:
        assert model in MODEL_TO_QUEUE


def test_queue_names_are_unique():
    assert len(set(MODEL_TO_QUEUE.values())) == len(MODEL_TO_QUEUE)


def test_queue_names_are_lowercase_and_dot_safe():
    for q in MODEL_TO_QUEUE.values():
        assert q == q.lower()
        assert ":" not in q
        assert "." not in q


def test_queue_for_model_prefixes_correctly():
    assert queue_for_model("qwen3:8b") == "q.extract.qwen3_8b"
    assert queue_for_model("medgemma:27b") == "q.extract.medgemma_27b"
    assert queue_for_model("deepseek-r1:32b") == "q.extract.deepseek_r1_32b"
    assert queue_for_model("llama3.1:8b") == "q.extract.llama3_1_8b"


def test_queue_for_unknown_model_raises():
    with pytest.raises(KeyError):
        queue_for_model("gpt-99:1t")
