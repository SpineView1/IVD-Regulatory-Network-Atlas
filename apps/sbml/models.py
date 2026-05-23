"""sbml models — ModelVersion and ExportArtifact.

ModelVersion is the immutable snapshot row described in spec §3:
    "SBML generation reads the current edge set, writes the file to MinIO,
     freezes the version."

Once ``frozen_at`` is non-NULL no other field is mutated. Curators view
``frozen_at IS NOT NULL`` rows as "this is what was downloaded".
"""

from __future__ import annotations

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import TimestampedModel

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def validate_semver(value: str) -> None:
    """Raise ValidationError if *value* is not a valid MAJOR.MINOR.PATCH string."""
    if not SEMVER_RE.match(value):
        raise ValidationError(f"{value!r} is not a valid MAJOR.MINOR.PATCH semver string")


class ModelVersion(TimestampedModel):
    """One row per ``(network, semver)`` — immutable after ``freeze()``.

    The combination of ``generated_from_edges`` (M2M to the exact edge IDs
    used) and the three S3 keys gives a fully reproducible artifact: the
    same edge set written through the same builder code produces a
    byte-identical SBML file.
    """

    network = models.ForeignKey(
        "networks.Network",
        on_delete=models.PROTECT,
        related_name="versions",
    )
    semver = models.CharField(max_length=32, validators=[validate_semver])
    frozen_at = models.DateTimeField(null=True, blank=True, db_index=True)

    n_species = models.PositiveIntegerField()
    n_reactions = models.PositiveIntegerField()
    n_edges = models.PositiveIntegerField()

    sbml_s3_key = models.CharField(max_length=512, blank=True)
    csv_s3_key = models.CharField(max_length=512, blank=True)  # edges.csv
    evidence_csv_s3_key = models.CharField(max_length=512, blank=True)  # evidence.csv
    zip_s3_key = models.CharField(max_length=512, blank=True)

    generated_from_edges = models.ManyToManyField(
        "graph.Edge",
        related_name="model_versions",
        blank=True,
    )

    generation_error = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["network", "semver"],
                name="uniq_modelversion_network_semver",
            ),
        ]
        indexes = [
            models.Index(fields=["network", "-created_at"]),
        ]
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"{self.network.code} v{self.semver}"

    def freeze(self) -> None:
        """Set ``frozen_at`` to now (idempotent — subsequent calls are no-ops)."""
        if self.frozen_at is None:
            self.frozen_at = timezone.now()
            self.save(update_fields=["frozen_at", "updated_at"])

    @classmethod
    def latest_for(cls, network: models.Model) -> ModelVersion | None:
        """Return the highest-semver ``ModelVersion`` for the given network.

        Sorting is done in Python (not DB) so we get true semver ordering rather
        than lexicographic ordering (which would put "0.9.0" > "0.10.0").
        """
        rows = list(cls.objects.filter(network=network))
        if not rows:
            return None
        rows.sort(key=lambda r: tuple(int(p) for p in r.semver.split(".")))
        return rows[-1]


class ExportArtifact(TimestampedModel):
    """Audit log of every artifact download.  Append-only."""

    ARTIFACT_TYPES = [
        ("sbml", "SBML-qual document"),
        ("edges_csv", "edges.csv"),
        ("evidence_csv", "evidence.csv"),
        ("zip", "Per-version ZIP bundle"),
    ]

    model_version = models.ForeignKey(
        ModelVersion,
        on_delete=models.PROTECT,
        related_name="downloads",
    )
    downloaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="sbml_downloads",
    )
    downloaded_at = models.DateTimeField(auto_now_add=True, db_index=True)
    artifact_type = models.CharField(max_length=16, choices=ARTIFACT_TYPES)
    s3_key = models.CharField(max_length=512)
    user_agent = models.CharField(max_length=512, blank=True)
    remote_addr = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-downloaded_at"]
        indexes = [
            models.Index(fields=["model_version", "-downloaded_at"]),
        ]
