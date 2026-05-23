"""@require_token decorator — gates every outbound provider call.

Usage:

    @require_token("ncbi_eutils", cost=1)
    def esearch(term: str) -> bytes:
        return httpx.get(...).content

If the bucket has no tokens, raises :class:`RateLimitExceeded` with
``retry_after_seconds`` populated. Celery tasks catch this and re-enqueue
themselves with ``countdown=retry_after_seconds``.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypeVar

from schedule.models import RateLimitBucket

F = TypeVar("F", bound=Callable[..., Any])


class RateLimitExceeded(Exception):
    """Raised when a provider's token bucket is empty."""

    def __init__(self, provider: str, retry_after_seconds: float) -> None:
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"rate-limited on {provider}; retry in {retry_after_seconds:.2f}s")


def require_token(provider: str, *, cost: int = 1) -> Callable[[F], F]:
    """Decorator factory."""

    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                bucket = RateLimitBucket.objects.get(provider=provider)
            except RateLimitBucket.DoesNotExist as exc:
                raise RateLimitExceeded(provider, float("inf")) from exc
            if not bucket.consume(cost):
                raise RateLimitExceeded(provider, bucket.seconds_until_refill(cost))
            return func(*args, **kwargs)

        return wrapper  # type: ignore[return-value]

    return decorator
