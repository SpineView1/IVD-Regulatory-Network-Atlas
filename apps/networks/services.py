"""Public API for the networks app.

Other apps (corpus, papers, dashboard, ...) call functions here, not
the underlying models, per spec §2's boundary discipline.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from networks.models import Network


class NetworkNotFound(LookupError):
    """Raised by ``get_network`` when ``code`` does not exist."""


def get_network(code: str) -> Network:
    try:
        return Network.objects.get(code=code)
    except Network.DoesNotExist as exc:
        raise NetworkNotFound(code) from exc


def list_active_networks() -> Iterable[Network]:
    return Network.objects.filter(is_active=True).order_by("category", "code")


def networks_by_category() -> dict[str, list[Network]]:
    grouped: dict[str, list[Network]] = defaultdict(list)
    for n in list_active_networks():
        grouped[n.category].append(n)
    return dict(grouped)
