import time, traceback, redis
from django.conf import settings
from extract.tasks import _do_enqueue_pending_chunks

r = redis.Redis.from_url(settings.CELERY_BROKER_URL)
QUEUE = "q.extract.qwen3_8b"
LOW_WATER = 300          # only refill when the GPU queue drops below this
print("ENQUEUER (queue-aware) start", flush=True)
while True:
    try:
        depth = r.llen(QUEUE)
        if depth < LOW_WATER:
            res = _do_enqueue_pending_chunks(batch_size=2000)
            print(f"ENQUEUER refilled (depth was {depth}): +{sum(res.values())}", flush=True)
        else:
            print(f"ENQUEUER ok (depth {depth} >= {LOW_WATER}), skip", flush=True)
    except Exception:
        traceback.print_exc()
    time.sleep(180)
