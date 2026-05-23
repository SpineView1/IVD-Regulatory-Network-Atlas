"""Settings package. Selection happens via DJANGO_SETTINGS_MODULE env var.

- ``interactome.settings.dev`` is the local-development default.
- ``interactome.settings.production`` is what gunicorn loads in the
  container.

Never import ``base`` directly; always go through one of the leaf
modules so all overrides are applied consistently.
"""
