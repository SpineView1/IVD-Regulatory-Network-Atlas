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
SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30  # 30 days
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False

# CSRF trusted origins — required for HTTPS POSTs behind Caddy's TLS termination.
# Comma-separated full origins (scheme + host), e.g. https://interactome.simbiosys.sb.upf.edu
CSRF_TRUSTED_ORIGINS = [
    o.strip() for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",") if o.strip()
]

# No dev fallback user in production.
AUTHELIA_DEV_FAKE_USER = None
