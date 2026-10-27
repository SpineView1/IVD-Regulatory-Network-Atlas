"""Continuous integrator: grounds new RawPPI into edges + populates networks,
recording evidence. Runs in its own container with the Gilda cache resident."""
import time, django
django.setup()
from graph.tasks import integrate_pending  # noqa: E402
print("integrator loop starting (Gilda resident; integrate every 90s)", flush=True)
while True:
    try:
        r = integrate_pending()
        print(time.strftime("%H:%M:%S"), "integrate_pending ->", r, flush=True)
    except Exception as e:
        print("integrate error:", repr(e)[:200], flush=True)
    time.sleep(3)
