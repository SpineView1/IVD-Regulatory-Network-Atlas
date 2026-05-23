"""verify — biologist review queue, sign-off, notifications.

Spec reference: Section 2 (verify app boundary), Section 7 (sign-off
workflow + five UI screens). All rows in this app are append-only:
state changes are never UPDATEs, every change is a new row carrying
its own timestamp and reviewer FK.
"""
