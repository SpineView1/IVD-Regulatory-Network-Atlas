"""Production settings — everything secret comes from the environment."""

from __future__ import annotations

import os

from interactome.settings.base import *  # noqa: F401,F403

DEBUG = False
ALLOWED_HOSTS = os.environ["DJANGO_ALLOWED_HOSTS"].split(",")
SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

# Strict cookie + HTTPS settings — Caddy terminates TLS in front.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365  # 1 year for preload list eligibility
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
SECURE_CONTENT_TYPE_NOSNIFF = True
# SECURE_BROWSER_XSS_FILTER was removed in Django 4.0 (no-op in 5.x).
# X-XSS-Protection header is set at the Caddy layer via the header directive.
X_FRAME_OPTIONS = "DENY"

# CSRF trusted origins — required for HTTPS POSTs behind Caddy's TLS termination.
# Comma-separated full origins (scheme + host), e.g. https://interactome.simbiosys.sb.upf.edu
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

# No dev fallback user in production.
AUTHELIA_DEV_FAKE_USER = None

# === Email (SMTP) — Phase 5 verification notifications ===
EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
EMAIL_HOST = os.environ.get("EMAIL_HOST", "smtp.upf.edu")
EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = os.environ.get("EMAIL_USE_TLS", "true").lower() == "true"

# === Phase 7: Sentry — called here so both gunicorn (wsgi/asgi) and
# django-admin (management commands) get Sentry wired on settings load
# in production. wsgi.py + asgi.py also call sentry_init(service="web")
# explicitly; sentry_sdk.init is idempotent on repeated calls.
from core.observability import sentry_init as _sentry_init  # noqa: E402

_sentry_init(service="web")
