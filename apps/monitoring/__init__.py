"""monitoring — health alerts, feature flags, admin pause/resume.

This app is the operational nervous system of the continuous-service
runtime. It owns three concerns:

1. ``HealthAlert`` — every health-check failure becomes one row, never
   updated, so the alert history is its own audit trail.
2. ``FeatureFlag`` — single-row global toggles read by Beat tasks
   before they fire (e.g. ``INGESTION_PAUSED``).
3. The pause/resume admin UI — two POST endpoints behind the curator
   role group, wired into the dashboard nav.

Depends on: ``core``. Depended on by: ``corpus``, ``extract``,
``schedule``, ``dashboard``.
"""
