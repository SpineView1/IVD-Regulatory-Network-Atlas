"""Per-model Celery queue routing.

Per spec §6 (Celery topology), each Ollama model gets its own queue
``q.extract.<slug>`` and its own concurrency-1 worker process. The
slug is the model id with ``:`` and ``.`` and ``-`` collapsed into
``_`` so it's safe in queue names, container names, and Django
settings keys.
"""

from __future__ import annotations

from extract.prompts import SUPPORTED_OLLAMA_MODELS

_QUEUE_PREFIX = "q.extract."


def _slugify(model_id: str) -> str:
    return model_id.lower().replace(":", "_").replace(".", "_").replace("-", "_")


MODEL_TO_QUEUE: dict[str, str] = {m: _slugify(m) for m in SUPPORTED_OLLAMA_MODELS}


def queue_for_model(model: str) -> str:
    """Full Celery queue name (with prefix). Raises KeyError on unknown."""
    return _QUEUE_PREFIX + MODEL_TO_QUEUE[model]
