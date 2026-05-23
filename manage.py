#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import sys
from pathlib import Path


def main() -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parent / "apps"))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "interactome.settings.dev")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you in the Poetry shell?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
