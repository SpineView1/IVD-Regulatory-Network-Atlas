"""verify models — Review, Signoff, ReviewAssignment, Subscription, Notification.

All five models inherit from core.TimestampedModel for created_at /
updated_at columns. The Review model is append-only by convention:
services.record_review is the only public path that creates rows, and
it never UPDATEs an existing row.

Canonical field names (per cross-plan reconciliation doc):
- Review targets graph.Edge (field: relation) or graph.Conflict
- Signoff targets sbml.ModelVersion (frozen_at, not frozen)
- Network.title (not name)
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import TimestampedModel


class ReviewDecision(models.TextChoices):
    APPROVE = "approve", "Approve"
    REJECT = "reject", "Reject"
    DISCUSS = "discuss", "Needs discussion"
    ABSTAIN = "abstain", "Abstain"


class Review(TimestampedModel):
    """An append-only audit row recording one reviewer's decision at one
    point in time on either a single Edge or a single Conflict.

    Spec §3 / §7: "every state change is a new row, never an UPDATE".
    The latest row (by created_at) for a given (reviewer, edge) or
    (reviewer, conflict) tuple is the current decision.
    """

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="reviews",
    )
    edge = models.ForeignKey(
        "graph.Edge",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    conflict = models.ForeignKey(
        "graph.Conflict",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    decision = models.CharField(
        max_length=16,
        choices=ReviewDecision.choices,
    )
    comment = models.TextField(blank=True, default="")

    class Meta:
        indexes = [
            models.Index(fields=["edge", "created_at"]),
            models.Index(fields=["conflict", "created_at"]),
            models.Index(fields=["reviewer", "created_at"]),
        ]

    def clean(self) -> None:
        if self.edge is None and self.conflict is None:
            raise ValidationError("A Review must target either an Edge or a Conflict.")
        if self.edge is not None and self.conflict is not None:
            raise ValidationError("A Review cannot target both an Edge and a Conflict; choose one.")

    def __str__(self) -> str:
        target = self.edge or self.conflict
        return (
            f"{self.reviewer.username} {self.decision} {target} "
            f"@ {self.created_at:%Y-%m-%d %H:%M}"
        )


class Signoff(TimestampedModel):
    """A curator pinning a specific ModelVersion as the verified release
    for one network. One per (network, model_version) pair.

    Spec §7 sign-off state machine: a Signoff promotes the network from
    version_draft -> verified and triggers sbml.regenerate_network with
    triggered_by_curator=True (MAJOR semver bump).
    """

    network = models.ForeignKey(
        "networks.Network",
        on_delete=models.PROTECT,
        related_name="signoffs",
    )
    model_version = models.OneToOneField(
        "sbml.ModelVersion",
        on_delete=models.PROTECT,
        related_name="signoff",
    )
    signed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="signoffs",
    )
    notes = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["model_version"],
                name="verify_signoff_unique_per_version",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"Signoff {self.network.code} v{self.model_version.semver} "
            f"by {self.signed_by.username}"
        )


class ReviewerRole(models.TextChoices):
    CURATOR = "curator", "Curator"
    REVIEWER = "reviewer", "Reviewer"
    OBSERVER = "observer", "Observer"


class ReviewAssignment(TimestampedModel):
    """Assigns a reviewer to a network with a role.

    Curators can sign off; reviewers can record per-edge decisions but
    cannot sign off; observers see notifications only.
    """

    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="review_assignments",
    )
    network = models.ForeignKey(
        "networks.Network",
        on_delete=models.CASCADE,
        related_name="review_assignments",
    )
    role = models.CharField(
        max_length=16,
        choices=ReviewerRole.choices,
        default=ReviewerRole.REVIEWER,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["reviewer", "network"],
                name="verify_reviewassignment_unique",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reviewer.username} as {self.role} on {self.network.code}"


class Subscription(TimestampedModel):
    """A user subscribes to a network or a whole category for email +
    in-app notifications on state changes.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    network = models.ForeignKey(
        "networks.Network",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    category = models.CharField(max_length=64, blank=True, default="")
    email_enabled = models.BooleanField(default=True)
    inapp_enabled = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "network"],
                condition=models.Q(network__isnull=False),
                name="verify_subscription_unique_user_network",
            ),
            models.UniqueConstraint(
                fields=["user", "category"],
                condition=~models.Q(category=""),
                name="verify_subscription_unique_user_category",
            ),
        ]

    def clean(self) -> None:
        if self.network is None and not self.category:
            raise ValidationError("A Subscription must target either a network or a category.")


class NotificationEvent(models.TextChoices):
    NETWORK_STALE = "network_stale", "Network became stale"
    NETWORK_DISAGREEMENTS = "network_disagreements", "New disagreements on network"
    NETWORK_SIGNED_OFF = "network_signed_off", "Network was signed off"
    NEW_VERSION = "new_version", "New version published"


class Notification(TimestampedModel):
    """In-app notification row. Email is sent in addition via
    verify.tasks.notify; this row drives the nav-bar dropdown.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    network = models.ForeignKey(
        "networks.Network",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notifications",
    )
    event_type = models.CharField(max_length=32, choices=NotificationEvent.choices)
    message = models.TextField()
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "created_at"]),
            models.Index(fields=["user", "read_at"]),
        ]

    @property
    def is_read(self) -> bool:
        return self.read_at is not None

    def mark_read(self) -> None:
        if self.read_at is None:
            self.read_at = timezone.now()
            self.save(update_fields=["read_at", "updated_at"])

    def __str__(self) -> str:
        return f"Notification[{self.event_type}] → {self.user.username}"
