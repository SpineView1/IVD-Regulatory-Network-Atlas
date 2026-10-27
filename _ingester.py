import time
from corpus.clients.ncbi import NcbiClient
from corpus.pubmed_query import MASTER_IDD_QUERY
from corpus.tasks import ingest_paper
from corpus.models import Paper

DONE = {"ingested", "classified", "fetched"}
print("INGESTER: esearch_all (year-windowed)...", flush=True)
pmids = NcbiClient().esearch_all(query=MASTER_IDD_QUERY, max_results=40000)
print(f"INGESTER: {len(pmids)} pmids total", flush=True)
have = set(Paper.objects.filter(pmid__in=pmids, ingest_status__in=DONE).values_list("pmid", flat=True))
todo = [p for p in pmids if p not in have]
print(f"INGESTER: {len(todo)} to ingest ({len(have)} already done)", flush=True)
n = ok = err = 0
for pmid in todo:
    try:
        ingest_paper.run(pmid)
        ok += 1
    except Exception as e:
        err += 1
        if err <= 5:
            print(f"INGESTER: err pmid={pmid}: {type(e).__name__} {str(e)[:80]}", flush=True)
    n += 1
    if n % 200 == 0:
        print(f"INGESTER: progress {n}/{len(todo)} ok={ok} err={err}", flush=True)
print(f"INGESTER: DONE n={n} ok={ok} err={err}", flush=True)
