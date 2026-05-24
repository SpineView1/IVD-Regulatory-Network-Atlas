# First Biologist Sign-off Ceremony

> **Purpose:** This is the Phase 7 closeout milestone. The first curator-driven MAJOR sign-off proves the whole pipeline — corpus → extraction → integration → SBML → review — operates as designed, end-to-end, under a real human's hands. The artifact this ceremony produces (`<network>_v1.0.0.zip`) is what gets shown to the professor.

---

## Pre-ceremony checklist

Run through this BEFORE convening the curator. Each item must be a checked box.

- [ ] Phase 5 verification UI is live and reviewers can resolve disagreements
- [ ] At least one network has reached `VERSION_DRAFT` status with a frozen `ModelVersion`
- [ ] Recommended first network: **`nfkb_axis_mmp_adamts`** (highest evidence density per Phase 1 corpus stats)
- [ ] Curator-of-record: Francis Chemorion (`fchemorion`) or designated alternate biologist
- [ ] Sentry DSN configured and verified receiving events (Task 3)
- [ ] pgbackrest has at least one successful backup recorded:
  ```bash
  docker compose exec pgbackrest pgbackrest --stanza=interactome info
  ```
  Expect a `full` entry within the last 7 days.
- [ ] `/metrics/` endpoint responds:
  ```bash
  curl -s http://localhost:8000/metrics/ | grep interactome_celery_queue_depth | head -3
  ```

---

## Ceremony procedure

### Step 1: Pre-flight (curator-led, 5 min)

The curator opens `/networks/nfkb_axis_mmp_adamts` and:

1. Confirms the graph rendering — Cytoscape.js shows all `accepted` edges with sensible layout.
2. Opens `/networks/nfkb_axis_mmp_adamts/disagreements` and confirms the disagreement count is zero. If non-zero, the ceremony cannot proceed — go review remaining disagreements first.
3. Reviews the version panel and notes the current draft semver (e.g. `v0.3.2`).

### Step 2: Cut the MAJOR version (curator-led, 2 min)

The curator clicks **Cut MAJOR version (sign off)** on the network detail page, acknowledges the modal, and clicks **Confirm**.

Behind the scenes the system runs the equivalent of:

```bash
docker compose exec web python manage.py signoff_ceremony \
    nfkb_axis_mmp_adamts fchemorion
```

The `signoff_ceremony` management command:
1. Validates the network is at `version_draft` status.
2. Finds the latest frozen `ModelVersion`.
3. Calls `verify.services.sign_off(network=..., model_version=..., signed_by=...)`.
4. `sign_off` creates a `Signoff` row, transitions the network to `verified`, and enqueues `sbml.tasks.regenerate(network.pk, triggered_by_curator=True)` for the MAJOR semver bump.

### Step 3: Verification (ops-led, 3 min)

```bash
# Verify the new version landed.
docker compose exec web python manage.py shell -c "
from networks.models import Network
from sbml.models import ModelVersion
n = Network.objects.get(code='nfkb_axis_mmp_adamts')
mv = ModelVersion.objects.filter(network=n).order_by('-id').first()
print(f'status={n.pipeline_status}')
print(f'semver={mv.semver}')
print(f'frozen_at={mv.frozen_at}')
print(f'zip_s3_key={mv.zip_s3_key}')
"
```

**Expected output:**
```
status=verified
semver=1.0.0
frozen_at=2026-...
zip_s3_key=sbml-artifacts/nfkb_axis_mmp_adamts/v1.0.0/...
```

```bash
# Verify the MinIO artifact is downloadable.
curl -sk https://interactome.simbiosys.sb.upf.edu/networks/nfkb_axis_mmp_adamts/v/1.0.0/download \
    -o /tmp/nfkb_v1.zip
unzip -l /tmp/nfkb_v1.zip
```

**Expected output:** four entries — `nfkb_axis_mmp_adamts.sbml`, `edges.csv`, `evidence.csv`, `README.md`.

```bash
# Verify the SBML is loadable by libsbml.
docker compose exec web python -c "
import libsbml, zipfile, io
with zipfile.ZipFile('/tmp/nfkb_v1.zip') as z:
    sbml_bytes = z.read('nfkb_axis_mmp_adamts.sbml')
reader = libsbml.SBMLReader()
doc = reader.readSBMLFromString(sbml_bytes.decode())
print(f'errors: {doc.getNumErrors()}')
print(f'model: {doc.getModel().getId() if doc.getModel() else None}')
"
```

**Expected output:**
```
errors: 0
model: nfkb_axis_mmp_adamts_v1_0_0
```

### Step 4: Subscriber notification (automatic)

The `verify.services.sign_off` call inside the ceremony emits in-app and email notifications to every subscribed reviewer. Confirm the curator received the notification at their UPF address. Subject should match:

```
[Interactome] nfkb_axis_mmp_adamts has been signed off as v1.0.0
```

### Step 5: Recording

Append a row to the ceremony log in this file (`docs/signoff-ceremony.md`) under the "Ceremony record" section below:

```
| YYYY-MM-DD | nfkb_axis_mmp_adamts | fchemorion | v1.0.0 | <zip_s3_key> | PASSED |
```

---

## Ceremony record

| Date | Network | Curator | Semver | MinIO key (zip_s3_key) | Outcome |
|------|---------|---------|--------|------------------------|---------|
| (to be filled in by the first ceremony) | | | | | |

---

## If the ceremony fails

| Symptom | Likely cause | Recovery |
|---------|-------------|---------|
| `signoff_ceremony` raises `must be in version_draft` | Network was already verified, or never made it past `STALE` | Resolve open disagreements, wait for nightly regen, retry |
| `sign_off` raises `InvalidTransition` | Network in wrong state (e.g. `idle`, `stale`) | Check `network.pipeline_status` in Django shell; force `version_draft` only if safe |
| SBML regenerate raises an error | Bad MIRIAM URI in an edge annotation | Inspect the offending edge in Django shell; fix `canonical_uri` and retry |
| `notify_subscribers` raises SMTP error | Mail relay outage | Re-run notify step in Django shell; ceremony sign-off itself is already committed |
| `pgbackrest info` shows no backups | pgbackrest container has been failing silently | See runbook procedure B; do NOT proceed with sign-off until backups are healthy |
| `--dry-run` passes but commit mode fails | Race condition (another agent changed network state) | Re-run with `--dry-run` to confirm state, then commit |

---

## After the ceremony

1. Append a record row to the "Ceremony record" table above.
2. Update the project memory note: "Phase 7 closed: first sign-off ceremony for nfkb_axis_mmp_adamts ran YYYY-MM-DD, v1.0.0 frozen."
3. Send the deployment summary email to the professor (template in `docs/deployment-summary-email.md`).
4. Tag the repo `v1.0.0` using `scripts/tag-v1-release.sh` (after all guards pass).
