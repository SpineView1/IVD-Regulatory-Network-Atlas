"""Custom template tags and filters for the dashboard.

Tags:
- ``status_pill``  — render a Bootstrap-styled badge for a pipeline status
- ``belief_color`` — filter: return a hex color string for a belief score
"""

from __future__ import annotations

from django import template
from django.utils.html import format_html

register = template.Library()

# Map pipeline_status → Bootstrap bg-* class (Bootstrap 5.3)
_STATUS_CLASSES: dict[str, str] = {
    "idle": "secondary",
    "refreshing": "info",
    "stale": "warning",
    "version_draft": "primary",
    "verified": "success",
    # Edge statuses used on the network detail view
    "candidate": "secondary",
    "accepted": "success",
    "conflicted": "danger",
    "rejected": "dark",
}


@register.simple_tag
def status_pill(status: str) -> str:
    """Render a Bootstrap badge <span> for the given status string.

    Usage::

        {% load dashboard_extras %}
        {% status_pill network.pipeline_status %}
    """
    css_class = _STATUS_CLASSES.get(status, "secondary")
    return format_html(
        '<span class="badge bg-{} status-pill">{}</span>',
        css_class,
        status,
    )


# Thresholds for belief score color coding
_HIGH_THRESHOLD = 0.7
_LOW_THRESHOLD = 0.4

# Colors chosen to match Bootstrap 5.3 semantic colors
_COLOR_HIGH = "#198754"  # Bootstrap success green
_COLOR_MED = "#fd7e14"   # Bootstrap warning orange
_COLOR_LOW = "#dc3545"   # Bootstrap danger red


@register.filter(name="belief_color")
def belief_color(score: float) -> str:  # noqa: D401 — simple filter
    """Return a hex color string for a belief score.

    - score >= 0.7 → green (#198754)
    - 0.4 <= score < 0.7 → orange (#fd7e14)
    - score < 0.4 → red (#dc3545)

    Usage::

        {% load dashboard_extras %}
        <span style="color: {{ edge.belief_score|belief_color }}">{{ edge.belief_score }}</span>
    """
    try:
        f = float(score)
    except (TypeError, ValueError):
        return _COLOR_MED
    if f >= _HIGH_THRESHOLD:
        return _COLOR_HIGH
    if f >= _LOW_THRESHOLD:
        return _COLOR_MED
    return _COLOR_LOW
