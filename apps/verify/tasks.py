"""verify Celery tasks — notification email dispatch + reviewer reminders.

``notify`` is the async email sender enqueued by
``verify.services._dispatch_notifications``. The in-app ``Notification`` rows
are created synchronously in ``services``; this task only renders + sends the
matching email (the queue hop keeps SMTP latency off the request path).

``dispatch_review_assignments`` is a Beat task (hourly, spec §6) that reminds
every curator about networks awaiting their review.

``auto_resolve`` is a medgemma:27b LLM task (q.extract.medgemma_27b queue)
that re-reads the source chunk for a Conflict and resolves it if confident.

``sweep_open_conflicts`` is a Beat task (every 30 min) that enqueues
``auto_resolve`` for open conflicts older than 1 hour.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from celery import shared_task
from verify.emails import render_event_email
from verify.models import Notification, NotificationEvent, ReviewAssignment

log = logging.getLogger(__name__)
User = get_user_model()


@shared_task(name="verify.notify", queue="q.io")
def notify(
    *,
    notification_id: int | None = None,
    user_id: int | None = None,
    network_id: int | None = None,
    event_type: str | None = None,
    message: str | None = None,
) -> str:
    """Send the email for one notification.

    Two call shapes (see ``services._dispatch_notifications``):
    - ``notify(notification_id=<pk>)`` — an in-app Notification already exists;
      derive the recipient + content from it.
    - ``notify(user_id=, network_id=, event_type=, message=)`` — email-only
      subscriber with no Notification row.
    """
    from networks.models import Network  # noqa: PLC0415 — avoid app-load import cycle

    if notification_id is not None:
        notif = Notification.objects.select_related("user", "network").get(pk=notification_id)
        recipient = notif.user
        network = notif.network
        ev = notif.event_type
        msg = notif.message
    else:
        if user_id is None or network_id is None or event_type is None:
            raise ValueError("notify: supply notification_id, or user_id+network_id+event_type.")
        recipient = User.objects.get(pk=user_id)
        network = Network.objects.get(pk=network_id)
        ev = event_type
        msg = message or ""

    email = getattr(recipient, "email", "")
    if not email or network is None:
        return "skipped"

    subject, body = render_event_email(event_type=ev, network=network, message=msg, user=recipient)
    send_mail(
        subject=subject,
        message=body,
        from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None),
        recipient_list=[email],
        fail_silently=False,
    )
    return "sent"


@shared_task(name="verify.dispatch_review_assignments", queue="q.io")
def dispatch_review_assignments() -> int:
    """Hourly: remind every curator about networks awaiting their review.

    Targets networks in ``version_draft`` (ready to sign off) or ``stale``
    (disagreements to resolve). Skips ``idle``/``verified``/``refreshing``
    networks. Creates an in-app Notification per curator and enqueues its
    email. Returns the number of reminders fired.
    """
    from verify import services  # noqa: PLC0415 — avoid app-load import cycle

    pending = ReviewAssignment.objects.filter(
        role="curator",
        network__pipeline_status__in=["version_draft", "stale"],
    ).select_related("reviewer", "network")

    count = 0
    for ra in pending:
        network = ra.network
        if network.pipeline_status == "stale":
            event_type = NotificationEvent.NETWORK_DISAGREEMENTS
            message = (
                f"Reminder: {network.title} is stale and has disagreements "
                f"awaiting your review."
            )
        else:
            event_type = NotificationEvent.NEW_VERSION
            message = f"Reminder: {network.title} has a draft version awaiting your " f"sign-off."
        services.notify_user(
            user=ra.reviewer,
            network=network,
            event_type=event_type,
            message=message,
        )
        count += 1
    return count


# ---------------------------------------------------------------------------
# Auto-conflict resolver (Phase 6 Task 8)
# ---------------------------------------------------------------------------


def _call_medgemma_for_reread(prompt: str) -> dict:
    """Issue a single Ollama call to medgemma:27b with schema-constrained output.

    Extracted into its own function so tests can patch it without
    monkey-patching Celery internals. The actual HTTP call delegates to
    ``core.ollama.OllamaClient`` (built in Phase 2) so token-budget and
    timeout semantics are shared.
    """
    from core.ollama import OllamaClient  # noqa: PLC0415 — lazy import

    client = OllamaClient(
        base_url=settings.OLLAMA_BASE_URL,
        authelia_base=settings.OLLAMA_AUTHELIA_BASE,
        username=settings.OLLAMA_USER,
        password=settings.OLLAMA_PASSWORD,
    )
    try:
        from verify.prompts import CONFLICT_REREAD_SCHEMA  # noqa: PLC0415

        response_text, _logprob, _eval_count = client.generate_structured(
            model="medgemma:27b",
            prompt=prompt,
            json_schema=CONFLICT_REREAD_SCHEMA,
            allowed_relations=list(CONFLICT_REREAD_SCHEMA["properties"]["relation"]["enum"]),
        )
        import json  # noqa: PLC0415

        return json.loads(response_text)
    finally:
        client.close()


@shared_task(name="conflict.auto_resolve", queue="q.extract.medgemma_27b", bind=True, max_retries=2)
def auto_resolve(self: Any, conflict_id: int) -> dict:
    """Re-read the source chunk and resolve a conflict if confidence is high.

    Sets ``Conflict.resolution_status='auto_resolved'`` when the medgemma
    re-read returns confidence >= AUTO_RESOLVE_CONFIDENCE_THRESHOLD;
    leaves it ``open`` (but records ``reasoning``) otherwise.

    Runs on the medgemma queue so the model stays hot.

    Reference: spec Section 10 (Phase 6 — auto-conflict resolver).
    """
    from graph.models import Conflict  # noqa: PLC0415 — lazy import
    from verify.prompts import (  # noqa: PLC0415
        AUTO_RESOLVE_CONFIDENCE_THRESHOLD,
        CONFLICT_REREAD_PROMPT,
    )

    with transaction.atomic():
        conflict = Conflict.objects.select_for_update().get(id=conflict_id)
        if conflict.resolution_status != "open":
            return {"skipped": True, "status": conflict.resolution_status}

    edge_a = conflict.edge_a
    edge_b = conflict.edge_b

    # Get one RawPPI from each edge to get model, confidence, relation, evidence_span
    ppi_a = edge_a.evidence.select_related("raw_ppi__run__chunk__section__paper").first()
    ppi_b = edge_b.evidence.select_related("raw_ppi__run__chunk__section__paper").first()

    if ppi_a is None or ppi_b is None:
        log.warning(
            "auto_resolve: conflict %d has edge(s) with no RawPPI evidence; skipping",
            conflict_id,
        )
        return {"skipped": True, "reason": "no_evidence"}

    raw_a = ppi_a.raw_ppi
    raw_b = ppi_b.raw_ppi
    chunk = raw_a.run.chunk
    paper = chunk.section.paper

    prompt = CONFLICT_REREAD_PROMPT.format(
        pmid=paper.pmid,
        section_doco_type=chunk.section.doco_type,
        chunk_text=chunk.text,
        subject_symbol=edge_a.source.symbol,
        subject_id=edge_a.source.canonical_uri,
        object_symbol=edge_a.target.symbol,
        object_id=edge_a.target.canonical_uri,
        model_a=raw_a.run.model_name,
        confidence_a=raw_a.confidence,
        relation_a=raw_a.relation,
        evidence_span_a=raw_a.evidence_span,
        model_b=raw_b.run.model_name,
        confidence_b=raw_b.confidence,
        relation_b=raw_b.relation,
        evidence_span_b=raw_b.evidence_span,
    )

    try:
        verdict = _call_medgemma_for_reread(prompt=prompt)
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60) from exc

    is_confident = verdict["confidence"] >= AUTO_RESOLVE_CONFIDENCE_THRESHOLD
    is_decisive = verdict["relation"] not in ("context_dependent", "no_relation")

    with transaction.atomic():
        conflict = Conflict.objects.select_for_update().get(id=conflict_id)
        conflict.reasoning = (
            f"medgemma:27b verdict (conf={verdict['confidence']:.2f}): "
            f"relation={verdict['relation']!r}. "
            f"Resolving text: {verdict['resolving_text']!r}. "
            f"Reasoning: {verdict['reasoning']}"
        )
        conflict.auto_resolve_attempted_at = timezone.now()

        if is_confident and is_decisive:
            conflict.resolution_status = "auto_resolved"
            conflict.resolved_relation = verdict["relation"]
            conflict.resolved_at = timezone.now()

        conflict.save()

    return {
        "conflict_id": conflict_id,
        "status": conflict.resolution_status,
        "confidence": verdict["confidence"],
    }


# ---------------------------------------------------------------------------
# Open-conflict sweeper (Phase 6 Task 9)
# ---------------------------------------------------------------------------

CONFLICT_SWEEP_BUFFER = timedelta(hours=1)


@shared_task(name="verify.sweep_open_conflicts", queue="q.io")
def sweep_open_conflicts() -> dict:
    """Every 30 min: enqueue auto_resolve for open conflicts older than 1 hour.

    The 1-hour buffer lets the integration worker detect cross-paper conflicts
    before the auto-resolver fires, reducing spurious "auto-resolved" rows on
    conflicts that will be superseded by fresh evidence.

    Returns ``{"dispatched": N}`` for logging.
    """
    from graph.models import Conflict  # noqa: PLC0415 — lazy import

    cutoff = timezone.now() - CONFLICT_SWEEP_BUFFER
    open_conflicts = Conflict.objects.filter(
        resolution_status="open",
        created_at__lt=cutoff,
    ).values_list("id", flat=True)

    dispatched = 0
    for cid in open_conflicts:
        auto_resolve.delay(cid)
        dispatched += 1

    log.info("sweep_open_conflicts: dispatched=%d", dispatched)
    return {"dispatched": dispatched}


# ---------------------------------------------------------------------------
# Daily disagreement digest (Phase 6 Task 10)
# ---------------------------------------------------------------------------


def queue_subscribers_for_disagreements(
    network_ids: list[int] | None = None,
) -> dict[int, dict[int, int]]:
    """Helper: collect recent open conflicts per (user_id, network_id).

    Returns ``{user_id: {network_id: conflict_count}}`` for all subscribers
    with recent (< 24 h) open conflicts in their subscribed networks.

    Separated into its own function so tests can call it directly.
    """
    from datetime import timedelta

    from django.db.models import Q

    from graph.models import Conflict, NetworkEdgeMembership  # noqa: PLC0415
    from verify.models import Subscription  # noqa: PLC0415 — lazy to avoid circularity

    cutoff = timezone.now() - timedelta(hours=24)

    # Build the network filter
    subs_qs = Subscription.objects.select_related("user", "network").filter(
        email_enabled=True,
    )
    if network_ids is not None:
        subs_qs = subs_qs.filter(network_id__in=network_ids)

    # Collect all relevant network ids from subscriptions (exclude null network)
    subs_qs = subs_qs.filter(network__isnull=False).exclude(user__email="")

    by_user: dict[int, dict[int, int]] = {}

    for sub in subs_qs:
        # Find open conflicts touching this network's edges within cutoff
        edge_ids = NetworkEdgeMembership.objects.filter(
            network=sub.network, edge__isnull=False
        ).values_list("edge_id", flat=True)
        n_conflicts = Conflict.objects.filter(
            Q(edge_a_id__in=edge_ids) | Q(edge_b_id__in=edge_ids),
            resolution_status="open",
            created_at__gte=cutoff,
        ).count()
        if n_conflicts == 0:
            continue
        if sub.network_id is not None:
            by_user.setdefault(sub.user_id, {})[sub.network_id] = n_conflicts

    return by_user


@shared_task(name="verify.notify_subscribers_daily_digest", queue="q.io")
def notify_subscribers_daily_digest() -> dict:
    """Daily 09:00 UTC: send one digest email per subscriber aggregating
    recent open disagreements across all subscribed networks.

    Creates one in-app Notification per (subscriber, network) pair that
    has fresh conflicts, then sends one summary email per subscriber.

    Returns ``{"sent": N}`` (N = number of unique subscribers who got email).
    """
    from django.core.mail import send_mail  # noqa: PLC0415 — lazy import

    from networks.models import Network  # noqa: PLC0415 — lazy import

    by_user = queue_subscribers_for_disagreements()

    sent = 0
    for user_id, net_counts in by_user.items():
        recipient = User.objects.get(pk=user_id)
        email = getattr(recipient, "email", "")
        if not email:
            continue

        # Create in-app Notification rows for each network with fresh conflicts
        for nid, count in net_counts.items():
            network = Network.objects.get(pk=nid)
            Notification.objects.create(
                user=recipient,
                network=network,
                event_type=NotificationEvent.NETWORK_DISAGREEMENTS,
                message=(
                    f"{count} new open disagreement(s) in '{network.title}' "
                    f"({network.code}) in the last 24 hours."
                ),
            )

        # Compose one aggregated email body
        body_lines = [
            f"Hi {getattr(recipient, 'first_name', None) or recipient.get_username()},",
            "",
            "New disagreements appeared in networks you subscribe to in the last 24h:",
            "",
        ]
        for nid, count in net_counts.items():
            network = Network.objects.get(pk=nid)
            body_lines.append(f"  - {network.title} ({network.code}): {count} new disagreement(s)")
        body_lines += [
            "",
            "Review at https://interactome.simbiosys.sb.upf.edu/",
        ]

        send_mail(
            subject="[interactome] Daily disagreement digest",
            message="\n".join(body_lines),
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "interactome@localhost"),
            recipient_list=[email],
            fail_silently=False,
        )
        sent += 1

    log.info("notify_subscribers_daily_digest: sent=%d", sent)
    return {"sent": sent}
