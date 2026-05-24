"""First-biologist sign-off ceremony management command.

Per spec Section 7 and Phase 7 plan Task 10:
  Scripted first-signoff with --dry-run mode (validates preconditions,
  prints what would happen) and a commit mode that calls
  ``verify.services.sign_off(...)`` — the canonical service boundary.

Usage::

    # Dry-run: validate preconditions only, no state change
    python manage.py signoff_ceremony nfkb_axis_mmp_adamts fchemorion --dry-run

    # Commit: run the full ceremony
    python manage.py signoff_ceremony nfkb_axis_mmp_adamts fchemorion

Critical contract (from CORRECTIONS section of phase brief):
- There is NO ``cut_major_version``. The ceremony uses
  ``verify.services.sign_off(network=, model_version=, signed_by=, notes=)``
  which creates a Signoff, transitions network version_draft → verified, and
  enqueues ``sbml.tasks.regenerate(network.pk, triggered_by_curator=True)``
  (the MAJOR bump).
- Network must be in ``version_draft`` before sign_off (else InvalidTransition).
- Requires a frozen ModelVersion to sign off against (latest frozen MV used).
"""

from __future__ import annotations

import argparse
import logging
from typing import Any

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from networks.models import Network
from sbml.models import ModelVersion
from verify.services import sign_off

log = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Run the curator sign-off ceremony on a network at VERSION_DRAFT. "
        "Use --dry-run to validate preconditions without making changes."
    )

    def add_arguments(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument(
            "network_code",
            help="Code of the network to sign off (e.g. nfkb_axis_mmp_adamts).",
        )
        parser.add_argument(
            "curator_username",
            help="Username of the curator-of-record.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            dest="dry_run",
            help="Validate preconditions only; do not create a Signoff or change state.",
        )
        parser.add_argument(
            "--notes",
            default="Phase 7 first-biologist sign-off ceremony.",
            help="Curator notes to store on the Signoff row.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        code: str = options["network_code"]
        username: str = options["curator_username"]
        dry_run: bool = options["dry_run"]
        notes: str = options["notes"]

        # --- Precondition 1: network exists ---
        try:
            network = Network.objects.get(code=code)
        except Network.DoesNotExist as exc:
            raise CommandError(f"network code '{code}' not found") from exc

        # --- Precondition 2: curator user exists ---
        User = get_user_model()
        try:
            curator = User.objects.get(username=username)
        except User.DoesNotExist as exc:
            raise CommandError(f"user '{username}' not found") from exc

        # --- Precondition 3: network is in version_draft ---
        if network.pipeline_status != "version_draft":
            raise CommandError(
                f"network '{code}' must be in version_draft state "
                f"(currently '{network.pipeline_status}')"
            )

        # --- Precondition 4: a frozen ModelVersion exists to sign off against ---
        frozen_mv = (
            ModelVersion.objects.filter(network=network)
            .exclude(frozen_at__isnull=True)
            .order_by("-created_at")
            .first()
        )
        if frozen_mv is None:
            raise CommandError(
                f"network '{code}' has no frozen ModelVersion — "
                "run sbml.regenerate first to produce a draft"
            )

        self.stdout.write(
            self.style.HTTP_INFO(
                f"Sign-off ceremony: network={code} curator={username} "
                f"model_version={frozen_mv.semver}"
            )
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"[DRY RUN] Would sign off {code} v{frozen_mv.semver} "
                    f"by {username}. No state changes made."
                )
            )
            return

        # --- Commit: call verify.services.sign_off ---
        try:
            signoff = sign_off(
                network=network,
                model_version=frozen_mv,
                signed_by=curator,
                notes=notes,
            )
        except Exception as exc:
            raise CommandError(f"sign_off failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Sign-off ceremony PASSED: {code} → verified "
                f"(Signoff pk={signoff.pk}, v{frozen_mv.semver})"
            )
        )
