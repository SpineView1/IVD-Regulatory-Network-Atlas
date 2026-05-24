# IVD Regulatory Network Atlas — Operations Runbook

> **Audience:** SIMBIOsys ops (Francis Chemorion, Javier).
> **Scope:** Production stack on `interactome.simbiosys.sb.upf.edu`.
> **Conventions:** Every procedure ends with a verification command + the expected output. If your output does not match the expected output, STOP and consult the linked spec section before continuing.

---

## A. Zero-downtime deploy

Use when shipping a new version of the application code with no schema-breaking changes.

```bash
# On the cluster host, as the deploy user:
cd /opt/interactome
git fetch origin
git checkout v1.X.Y                       # the tag to deploy
docker compose pull web beat worker_io worker_fast worker_extract_medgemma \
                     worker_extract_phi4 worker_extract_qwen3 worker_extract_gemma3 \
                     worker_extract_deepseek worker_extract_devstral worker_extract_llama
docker compose build web
docker compose up -d --no-deps web         # web boots, runs migrate, gunicorn replaces gracefully
docker compose up -d --no-deps beat worker_io worker_fast \
                     worker_extract_medgemma worker_extract_phi4 worker_extract_qwen3 \
                     worker_extract_gemma3 worker_extract_deepseek worker_extract_devstral \
                     worker_extract_llama
```

**Verify:**
```bash
curl -sk https://interactome.simbiosys.sb.upf.edu/health/ | jq -r '.database'
```
**Expected output:** `ok`

```bash
docker compose ps --format json | jq -r '.[] | select(.Health=="unhealthy") | .Service'
```
**Expected output:** (empty — no unhealthy services)

Spec reference: Section 9 "Deploy".

---

## B. Restore from backup

Use when the production Postgres database is corrupt, lost, or needs to be rolled back to a known point in time.

**RPO target: 15 min. RTO target: 30 min.** Per spec Section 8.

```bash
# 1. Stop writers.
docker compose stop web beat worker_io worker_fast \
    worker_extract_medgemma worker_extract_phi4 worker_extract_qwen3 \
    worker_extract_gemma3 worker_extract_deepseek worker_extract_devstral worker_extract_llama

# 2. Verify pgbackrest has a recent backup.
docker compose exec pgbackrest pgbackrest --stanza=interactome info

# 3. Stop postgres and wipe its data dir (data is in named volume; recreate it).
docker compose stop postgres
docker volume rm interactome_pgdata
docker compose up -d postgres
# Wait for the empty postgres to come up so pgbackrest can write into the dir.
sleep 10

# 4. Restore. For point-in-time, add --type=time --target='2026-05-19 14:00:00 UTC'.
docker compose exec pgbackrest pgbackrest --stanza=interactome \
    --delta --log-level-console=info restore

# 5. Restart everything.
docker compose up -d
```

**Verify:**
```bash
docker compose exec postgres psql -U interactome -d interactome -tAc \
    "SELECT count(*) FROM corpus_paper;"
```
**Expected output:** a positive integer ≥ 30000 (or whatever the corpus count was at the backup point — confirm against the pre-incident snapshot).

```bash
curl -sk https://interactome.simbiosys.sb.upf.edu/health/ | jq -r '.database'
```
**Expected output:** `ok`

Spec reference: Section 8 "Disaster recovery".

---

## C. Cluster host hardware failure

Use when the cluster host running the stack has died (disk failure, motherboard, mainboard, etc.) and a replacement host has been provisioned by IT.

**Precondition:** weekly `rsync-offhost.sh` has been running successfully — `backupdata` and `miniodata` are on the off-host target.

```bash
# 1. On the new host, install Docker + docker compose v2.
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker

# 2. Restore the backupdata volume from the off-host target.
sudo mkdir -p /var/lib/docker/volumes/interactome_backupdata/_data
sudo rsync -avz backup@backup.simbiosys.sb.upf.edu:/data/interactome/backupdata/ \
    /var/lib/docker/volumes/interactome_backupdata/_data/

# 3. Restore miniodata identically.
sudo mkdir -p /var/lib/docker/volumes/interactome_miniodata/_data
sudo rsync -avz backup@backup.simbiosys.sb.upf.edu:/data/interactome/miniodata/ \
    /var/lib/docker/volumes/interactome_miniodata/_data/

# 4. Clone the repo and configure .env.
git clone git@github.com:SpineView1/IVD-Regulatory-Network-Atlas.git /opt/interactome
cd /opt/interactome
git checkout v1.X.Y
sudo cp /etc/interactome/.env .env       # the env file restored separately by ops

# 5. Bring up postgres + pgbackrest and run restore (see procedure B step 4).
docker compose up -d postgres
sleep 10
docker compose exec pgbackrest pgbackrest --stanza=interactome --delta restore

# 6. Bring the rest of the stack up.
docker compose up -d
```

**Verify:**
```bash
curl -sk https://interactome.simbiosys.sb.upf.edu/health/ | jq
```
**Expected output:**
```json
{"user": "fchemorion", "database": "ok"}
```

Spec reference: Section 8 "Cold restart procedure" + Section 9 "Asks for IT".

---

## D. Ollama gateway outage

Use when Ollama at `ollama.simbiosys.sb.upf.edu` is returning 5xx or timing out and the extractor queues are backing up.

```bash
# 1. Confirm the outage — should be 502/504 or connection refused.
curl -ksv -X POST https://ollama.simbiosys.sb.upf.edu/api/generate \
    -H 'Content-Type: application/json' \
    -d '{"model":"qwen3:8b","prompt":"hi"}' 2>&1 | head -20

# 2. Pause the seven extract workers so retries don't pile up.
docker compose stop worker_extract_medgemma worker_extract_phi4 worker_extract_qwen3 \
    worker_extract_gemma3 worker_extract_deepseek worker_extract_devstral worker_extract_llama

# 3. Confirm queue depth is stable (no more retries firing).
docker compose exec redis redis-cli LLEN q.extract.qwen3_8b

# 4. Notify Javier (IT) at it.simbiosys@upf.edu, including the curl output from step 1.

# 5. After Ollama is restored, resume workers.
docker compose start worker_extract_medgemma worker_extract_phi4 worker_extract_qwen3 \
    worker_extract_gemma3 worker_extract_deepseek worker_extract_devstral worker_extract_llama

# 6. Watch the queues drain.
watch -n 5 'docker compose exec redis redis-cli LLEN q.extract.qwen3_8b'
```

**Verify:**
```bash
curl -ks https://ollama.simbiosys.sb.upf.edu/api/tags | jq '.models | length'
```
**Expected output:** an integer ≥ 7 (the seven extraction models registered).

Spec reference: Section 6 "Failure / observability".

---

## E. Full system bring-up from a clean machine

Use during initial deployment by IT, or after a complete teardown/rebuild for an upgrade.

```bash
# 1. Provision per spec Section 9 "Asks for IT":
#      - Docker 24+, ≥ 32 GB RAM, ≥ 200 GB disk
#      - DNS A record interactome.simbiosys.sb.upf.edu → host internal IP
#      - Authelia rule + AD group simbiosys-lab:
#          access_control:
#            rules:
#              - domain: interactome.simbiosys.sb.upf.edu
#                policy: one_factor
#                subject:
#                  - "group:simbiosys-lab"

# 2. Clone the repo.
git clone git@github.com:SpineView1/IVD-Regulatory-Network-Atlas.git /opt/interactome
cd /opt/interactome
git checkout v1.0.0

# 3. Configure .env (chmod 600).
cp .env.example .env
$EDITOR .env
chmod 600 .env

# 4. Create the host log directory.
sudo mkdir -p /var/log/interactome
sudo chmod 0750 /var/log/interactome

# 5. Bring up the data tier first.
docker compose up -d postgres redis minio grobid
docker compose ps      # all four should be healthy

# 6. Bring up pgbackrest — it creates the stanza on first run.
docker compose up -d pgbackrest
docker compose logs --tail 40 pgbackrest

# 7. Bring up the application tier.
docker compose up -d web beat worker_io worker_fast \
    worker_extract_medgemma worker_extract_phi4 worker_extract_qwen3 \
    worker_extract_gemma3 worker_extract_deepseek worker_extract_devstral worker_extract_llama

# 8. Bring up the observability tier.
docker compose up -d prometheus grafana

# 9. Bring up the edge tier.
docker compose up -d caddy

# 10. Seed initial data: networks taxonomy.
docker compose exec web python manage.py loaddata networks/fixtures/0001_taxonomy.yaml
```

**Verify:**
```bash
curl -sk https://interactome.simbiosys.sb.upf.edu/health/ | jq
```
**Expected output:**
```json
{"user": "<your-username>", "database": "ok"}
```

```bash
docker compose ps --format '{{.Service}} {{.Status}}' | sort
```
**Expected output:** 18–20 lines, each ending with `Up` or `Up (healthy)`.

Spec reference: Section 9 in full.

---

## F. Authelia / LDAP outage

Use when curators report "I can't log in" and `https://authelia.simbiosys.sb.upf.edu` is unresponsive or returning 5xx.

The stack itself stays UP — Caddy will block external traffic, but background Celery work, scheduled tasks, and the API continue. Curator workflows pause.

```bash
# 1. Confirm Authelia is unhealthy (not us).
curl -ksv https://authelia.simbiosys.sb.upf.edu/api/state 2>&1 | tail -20

# 2. Confirm OUR stack is still healthy from inside (bypassing Caddy).
docker compose exec web curl -s http://localhost:8000/health/

# 3. Notify Javier (IT) at it.simbiosys@upf.edu.
#    Authelia + LDAP recovery is IT-owned, not ours.

# 4. Emergency note on local-auth bypass:
#    AUTHELIA_DEV_FAKE_USER is always None in production.
#    Do NOT enable it as a workaround — it disables all auth entirely.

# 5. After Authelia is restored, sanity-check the SSO flow.
curl -skI https://interactome.simbiosys.sb.upf.edu/health/    # should 302 to Authelia login
```

**Verify:**
```bash
curl -ksI https://authelia.simbiosys.sb.upf.edu/api/state | head -1
```
**Expected output:** `HTTP/2 200`

```bash
docker compose exec web curl -s http://localhost:8000/health/ | jq -r '.database'
```
**Expected output:** `ok` (proves the app stayed up through the outage).

Spec reference: Section 9 "Authelia integration".

---

## Appendix: Useful diagnostic commands

```bash
# Queue depth across all extract queues
docker compose exec redis redis-cli \
    EVAL "local r={}; for _,k in ipairs(KEYS) do r[#r+1] = k..'='..redis.call('LLEN', k) end; return r" \
    9 q.io q.fast q.extract.medgemma_27b q.extract.phi4_14b q.extract.qwen3_8b \
    q.extract.gemma3_12b q.extract.deepseek_r1_32b q.extract.devstral_24b q.extract.llama3_1_8b

# Latest pgbackrest backup info
docker compose exec pgbackrest pgbackrest --stanza=interactome info

# Recent Sentry events (if SENTRY_DSN configured)
# Check https://sentry.io/organizations/simbiosys/issues/?project=interactome

# Prometheus targets health
docker compose exec prometheus wget -qO- http://localhost:9090/api/v1/targets \
    | python3 -c "import sys, json; d=json.load(sys.stdin); \
      print({t['labels']['job']: t['health'] for t in d['data']['activeTargets']})"

# Last healthcheck run
docker compose exec web python manage.py shell -c \
    "from schedule.models import HealthcheckState; s=HealthcheckState.objects.get(id=1); print(s.last_run_at)"

# Tail structured JSON logs
tail -f /var/log/interactome/app.jsonl | python3 -c \
    "import sys, json; [print(json.dumps(json.loads(l), indent=2)) for l in sys.stdin]"
```
