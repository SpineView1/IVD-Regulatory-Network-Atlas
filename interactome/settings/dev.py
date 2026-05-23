"""Development settings."""
from __future__ import annotations

from interactome.settings.base import *  # noqa: F401,F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
SECRET_KEY = "dev-secret-not-for-production"

# Allow the Authelia middleware to short-circuit to a fake user in dev
# when no Remote-User header is present.
AUTHELIA_DEV_FAKE_USER = "fchemorion"

EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"

# Disable HTTPS-only cookies in dev.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
