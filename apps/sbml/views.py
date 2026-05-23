"""sbml HTTP views — artifact downloads."""

from __future__ import annotations

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET

from core.storage import get_object_store
from sbml.models import ExportArtifact, ModelVersion

_TYPE_TO_FIELD: dict[str, tuple[str, str]] = {
    "zip": ("zip_s3_key", "zip"),
    "sbml": ("sbml_s3_key", "sbml"),
    "edges_csv": ("csv_s3_key", "edges_csv"),
    "evidence_csv": ("evidence_csv_s3_key", "evidence_csv"),
}


@require_GET
@login_required
def download_artifact(request: HttpRequest, code: str, semver: str) -> HttpResponse:
    """Resolve the artifact for ``(network.code, semver)``, audit-log the
    download, and redirect to a presigned MinIO URL.
    """
    mv = get_object_or_404(
        ModelVersion.objects.select_related("network"),
        network__code=code,
        semver=semver,
        frozen_at__isnull=False,
    )
    artifact_type = request.GET.get("type", "zip")
    if artifact_type not in _TYPE_TO_FIELD:
        return HttpResponse(
            f"unknown artifact type {artifact_type!r}; " f"allowed: {sorted(_TYPE_TO_FIELD)}",
            status=400,
        )
    field, audit_type = _TYPE_TO_FIELD[artifact_type]
    key: str = getattr(mv, field)
    if not key:
        return HttpResponse(f"no {artifact_type} artifact for v{semver}", status=404)

    # request.user is guaranteed to be authenticated here (login_required above).
    assert isinstance(request.user, AbstractBaseUser)
    ExportArtifact.objects.create(
        model_version=mv,
        downloaded_by=request.user,
        artifact_type=audit_type,
        s3_key=key,
        user_agent=request.META.get("HTTP_USER_AGENT", "")[:512],
        remote_addr=_client_ip(request),
    )

    url = get_object_store().presigned_download_url(
        settings.MINIO_BUCKET_SBML,
        key,
    )
    return HttpResponseRedirect(url)


def _client_ip(request: HttpRequest) -> str | None:
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip() or None
    return request.META.get("REMOTE_ADDR") or None
