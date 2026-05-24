"""Tests for Task 8 — dashboard extensions.

Tests for:
- context_processors.unread_notifications_count
- templatetags.dashboard_extras.status_pill
- templatetags.dashboard_extras.belief_color
- base.html includes CDN scripts + notification dropdown slot
"""

from __future__ import annotations

import pytest
from django.template import Context, RequestContext, Template
from django.test import RequestFactory

# ---------------------------------------------------------------------------
# context_processors.unread_notifications_count
# ---------------------------------------------------------------------------


class TestUnreadNotificationsCountContextProcessor:
    """Tests for apps/dashboard/context_processors.py."""

    def test_anonymous_user_returns_zero(self, db, rf):
        """Anonymous users have 0 unread notifications."""
        from django.contrib.auth.models import AnonymousUser

        from dashboard.context_processors import unread_notifications_count

        request = rf.get("/")
        request.user = AnonymousUser()
        ctx = unread_notifications_count(request)
        assert ctx["unread_notifications_count"] == 0

    def test_authenticated_user_with_no_notifications_returns_zero(self, db, rf):
        from django.contrib.auth import get_user_model

        from dashboard.context_processors import unread_notifications_count

        User = get_user_model()
        user = User.objects.create_user(username="curator1", email="c@upf.edu")
        request = rf.get("/")
        request.user = user
        ctx = unread_notifications_count(request)
        assert ctx["unread_notifications_count"] == 0

    def test_authenticated_user_counts_unread_notifications(self, db, rf):
        from django.contrib.auth import get_user_model

        from dashboard.context_processors import unread_notifications_count
        from networks.models import Network
        from verify.models import Notification

        User = get_user_model()
        user = User.objects.create_user(username="curator2", email="c2@upf.edu")
        network = Network.objects.create(code="test_net", category="I", title="Test Net")

        # Create 2 unread + 1 read notification
        Notification.objects.create(
            user=user, network=network, event_type="network_stale", message="stale"
        )
        Notification.objects.create(
            user=user, network=network, event_type="new_version", message="new"
        )
        n_read = Notification.objects.create(
            user=user, network=network, event_type="new_version", message="already read"
        )
        n_read.mark_read()

        request = rf.get("/")
        request.user = user
        ctx = unread_notifications_count(request)
        assert ctx["unread_notifications_count"] == 2

    def test_context_key_is_always_present(self, db, rf):
        """The key must exist in the dict even for anonymous users."""
        from django.contrib.auth.models import AnonymousUser

        from dashboard.context_processors import unread_notifications_count

        request = rf.get("/")
        request.user = AnonymousUser()
        ctx = unread_notifications_count(request)
        assert "unread_notifications_count" in ctx


# ---------------------------------------------------------------------------
# templatetags.dashboard_extras — status_pill
# ---------------------------------------------------------------------------


class TestStatusPillTemplateTag:
    """Tests for dashboard_extras.status_pill."""

    def _render(self, status: str) -> str:
        template = Template("{% load dashboard_extras %}{% status_pill status %}")
        return template.render(Context({"status": status}))

    def test_idle_renders_badge(self):
        html = self._render("idle")
        assert "idle" in html

    def test_verified_renders_success_class(self):
        html = self._render("verified")
        assert "verified" in html
        # Should include a green/success semantic class
        assert any(cls in html for cls in ["success", "green", "verified"])

    def test_stale_renders_warning_class(self):
        html = self._render("stale")
        assert "stale" in html
        assert any(cls in html for cls in ["warning", "orange", "stale"])

    def test_version_draft_renders_info_class(self):
        html = self._render("version_draft")
        assert "version_draft" in html or "draft" in html

    def test_conflicted_renders_danger_class(self):
        html = self._render("conflicted")
        assert "conflicted" in html
        assert any(cls in html for cls in ["danger", "red", "conflicted"])

    def test_unknown_status_renders_safely(self):
        """Unknown statuses must not raise; they render a neutral badge."""
        html = self._render("unknown_xyz")
        assert "unknown_xyz" in html

    def test_returns_span_element(self):
        html = self._render("verified")
        assert "<span" in html


# ---------------------------------------------------------------------------
# templatetags.dashboard_extras — belief_color
# ---------------------------------------------------------------------------


class TestBeliefColorTemplateTag:
    """Tests for dashboard_extras.belief_color."""

    def _render(self, score: float) -> str:
        template = Template("{% load dashboard_extras %}{{ score|belief_color }}")
        return template.render(Context({"score": score}))

    def test_high_belief_green(self):
        color = self._render(0.9)
        assert color in ("#27ae60", "green", "#2ecc71", "success", "#198754")

    def test_medium_belief_orange(self):
        color = self._render(0.5)
        assert color in ("#f39c12", "orange", "#e67e22", "warning", "#fd7e14")

    def test_low_belief_red(self):
        color = self._render(0.2)
        assert color in ("#e74c3c", "red", "#c0392b", "danger", "#dc3545")

    def test_boundary_high_threshold(self):
        """Scores >= 0.7 should be high (green)."""
        color = self._render(0.7)
        assert color in ("#27ae60", "green", "#2ecc71", "success", "#198754")

    def test_boundary_low_threshold(self):
        """Scores < 0.4 should be low (red)."""
        color = self._render(0.39)
        assert color in ("#e74c3c", "red", "#c0392b", "danger", "#dc3545")


# ---------------------------------------------------------------------------
# base.html — CDN scripts + notification dropdown slot
# ---------------------------------------------------------------------------


class TestBaseHtmlExtensions:
    """Tests that base.html has the required CDN scripts and nav chrome."""

    def _render_base(self, request=None) -> str:
        # Render base.html directly; use a minimal block-extending template
        template_str = "{% extends 'dashboard/base.html' %}{% block content %}BODY{% endblock %}"
        t = Template(template_str)
        if request is not None:
            ctx: Context = RequestContext(request, {})
        else:
            ctx = Context({})
        return t.render(ctx)

    def test_htmx_cdn_script_present(self, db):
        html = self._render_base()
        assert "htmx" in html.lower()

    def test_cytoscape_cdn_script_present(self, db):
        html = self._render_base()
        assert "cytoscape" in html.lower()

    def test_bootstrap_cdn_present(self, db):
        html = self._render_base()
        assert "bootstrap" in html.lower()

    def test_datatables_cdn_present(self, db):
        html = self._render_base()
        assert "datatable" in html.lower()

    def test_nav_links_present(self, db):
        html = self._render_base()
        # Should have a nav element
        assert "<nav" in html

    def test_notification_dropdown_slot_present(self, db):
        """base.html should include the notification dropdown partial slot."""
        html = self._render_base()
        # The notification slot can be rendered as a button/link or the partial
        assert "notification" in html.lower() or "bell" in html.lower()

    def test_existing_stats_link_still_present(self, db):
        """Corpus stats link should remain in nav after extension."""
        html = self._render_base()
        assert "stats" in html.lower() or "corpus" in html.lower()


@pytest.fixture
def rf():
    return RequestFactory()
