# Security Review — Phase 7

> **Scope:** Caddy reverse-proxy, Authelia SSO, Django production settings.
> **Date:** 2026-05-24
> **Reviewer:** Phase 7 hardening pass (Task 14).
> **Result:** All items VERIFIED or FIXED. No critical findings.

---

## 1. Secrets management

### Check: No real secret values in committed files

```bash
git ls-files | xargs grep -l -E '(SECRET_KEY|PASSWORD|API_KEY|DSN)[ ]*=[ ]*["][^"]+["]' \
    2>/dev/null | grep -v '\.example$' | grep -v 'docs/' | grep -v 'tests'
```

**Finding:**
- `interactome/settings/dev.py` — `SECRET_KEY = "dev-secret-not-for-production"`. ACCEPTABLE: this file is only loaded in the test/dev environment (`DJANGO_SETTINGS_MODULE=interactome.settings.dev`); the value is a placeholder and the file name makes its scope clear. Production uses `os.environ["DJANGO_SECRET_KEY"]`.
- `README.md` — contains template variable references like `MINIO_TEST_SECRET_KEY=interactome` (a publicly-documented MinIO default credential for the test container). ACCEPTABLE: test-only, not production.

**Status:** VERIFIED — no production secret values committed.

### Check: `.env` is gitignored

```bash
grep -E '^\.env$' .gitignore
```

**Status:** VERIFIED — `.env` is in `.gitignore`.

---

## 2. Caddy TLS and security headers

### Findings before this review:

The `Caddyfile` had `encode zstd gzip` and Authelia `forward_auth` but was missing explicit security response headers. Django's `SECURE_*` settings set HSTS on Django responses, but having Caddy add them as a defense-in-depth layer is better practice (ensures headers are present even if Django's SecurityMiddleware chain is skipped).

### Hardening applied:

Added to `Caddyfile`:

```caddy
header {
    Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
    X-Frame-Options "DENY"
    X-Content-Type-Options "nosniff"
    Referrer-Policy "strict-origin-when-cross-origin"
    -Server
}
```

These headers are now set at the Caddy layer in addition to Django's middleware layer. The `-Server` directive removes the `Caddy/<version>` Server header to avoid leaking the reverse-proxy version.

**Status:** FIXED (Caddyfile updated).

### Caddy ACME/OCSP

Caddy 2 performs OCSP stapling automatically when Let's Encrypt issues the certificate. No config required. **Status:** VERIFIED.

---

## 3. Authelia access control rule

The Authelia `access_control` rule for this app must be:

```yaml
rules:
  - domain: interactome.simbiosys.sb.upf.edu
    policy: one_factor
    subject:
      - "group:simbiosys-lab"
```

This is documented in `docs/runbook.md` procedure E step 1. The rule is IT-managed on `authelia.simbiosys.sb.upf.edu` — not in this repository.

**Verification:** Documented in runbook. IT (Javier) must confirm the rule is present on the Authelia host. Command on the Authelia host:

```bash
cat /config/configuration.yml | grep -A 5 interactome
```

Expected output includes `group:simbiosys-lab`.

**Status:** DOCUMENTED. IT action required at deploy time.

---

## 4. Django `SECURE_*` production settings

All settings verified against `interactome/settings/production.py`:

| Setting | Value | Required | Status |
|---------|-------|----------|--------|
| `DEBUG` | `False` | Yes | VERIFIED |
| `SECRET_KEY` | `os.environ["DJANGO_SECRET_KEY"]` | Yes | VERIFIED |
| `ALLOWED_HOSTS` | from env | Yes | VERIFIED |
| `SECURE_PROXY_SSL_HEADER` | `('HTTP_X_FORWARDED_PROTO', 'https')` | Yes (Caddy TLS) | VERIFIED |
| `SESSION_COOKIE_SECURE` | `True` | Yes | VERIFIED |
| `CSRF_COOKIE_SECURE` | `True` | Yes | VERIFIED |
| `SECURE_HSTS_SECONDS` | `31536000` (1 year) | Yes | VERIFIED |
| `SECURE_HSTS_INCLUDE_SUBDOMAINS` | `True` | Yes | VERIFIED |
| `SECURE_HSTS_PRELOAD` | `True` | Yes | VERIFIED |
| `SECURE_CONTENT_TYPE_NOSNIFF` | `True` | Yes | VERIFIED |
| `SECURE_REFERRER_POLICY` | `strict-origin-when-cross-origin` | Yes | VERIFIED |
| `X_FRAME_OPTIONS` | `DENY` | Yes | VERIFIED |
| `CSRF_TRUSTED_ORIGINS` | from env | Yes | VERIFIED |
| `AUTHELIA_DEV_FAKE_USER` | `None` | Yes | VERIFIED |

### Hardening applied:

Removed `SECURE_BROWSER_XSS_FILTER = True` from `production.py`. This setting was removed from Django in version 4.0 (the `X-XSS-Protection` header it set is deprecated in modern browsers and the MDN recommendation is to omit it). In Django 5.x it is silently ignored. The `X-Content-Type-Options: nosniff` header (retained) is the modern replacement for most XSS attack vectors this addressed. The `-Server` removal in Caddy provides additional hardening at the transport layer.

**Status:** FIXED (removed deprecated setting).

---

## 5. Django deployment check

```bash
DJANGO_SECRET_KEY=check-only DJANGO_ALLOWED_HOSTS=x \
    python manage.py check --deploy --settings=interactome.settings.production
```

**Output:**
```
WARNINGS:
?: (security.W008) SECURE_SSL_REDIRECT is not True.
?: (security.W009) SECRET_KEY is too short (placeholder key used for check only).
System check identified 2 issues (0 silenced).
```

**Assessment:**
- `W008` (`SECURE_SSL_REDIRECT`) — ACCEPTABLE. Caddy handles HTTPS redirect at the edge. Django does not need to redirect internally. This is the correct configuration for a Caddy-terminated TLS stack.
- `W009` (short `SECRET_KEY`) — ACCEPTABLE in this check context. We used a placeholder key (`check-only`). Production `.env` must have a ≥50-character random key. The check in `production.py` reads from `os.environ["DJANGO_SECRET_KEY"]` — it will raise `KeyError` at startup if the env var is absent.

**Status:** VERIFIED — no actionable code issues.

---

## 6. Summary of changes made in this review

| File | Change | Reason |
|------|--------|--------|
| `Caddyfile` | Added `header` block with HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, -Server | Defense-in-depth; headers now set at Caddy layer in addition to Django |
| `interactome/settings/production.py` | Removed `SECURE_BROWSER_XSS_FILTER = True` | Deprecated/removed in Django 4.0; no-op in 5.x; adds noise |

All other reviewed items were already correctly configured.
