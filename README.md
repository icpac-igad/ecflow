# ECMWF IFS GIK — daily ecFlow workflow (ICPAC / E4DRR)

> This branch (`deployment`) is ICPAC's **E4DRR deployment fork of ecFlow**. It adds an
> always-on ecFlow deployment that runs the **ECMWF IFS ensemble GIK pipeline every day**,
> unattended, plus a monitoring dashboard and a Python-API suite generator. The upstream
> ecFlow project and its licence are noted at the bottom.

This README is the complete guide: what it does, how it is wired, how to operate it, and
how to fix it. The building blocks live under [`deployment/`](deployment/).

---

## 1. What it does

Every day at **07:00 UTC** the workflow ingests the ECMWF IFS ensemble forecast (control
+ 50 perturbed members = **51 members**) for that day's `00z` run and produces **51
GIK/Kerchunk parquet reference files** in Google Cloud Storage. Each parquet is a virtual
Zarr store whose chunks are byte-range references back into ECMWF's public GRIB2 archive
on AWS S3 — so the output is tiny (references, not data) while addressing the full run.

```
GCS output:  gs://gik-ecmwf-aws-tf/v20260623_run_par_ecmwf/YYYY/MM/YYYYMMDD/00z/*.parquet
             (51 files per date: control + ens_01 … ens_50)
```

A later stage (L3/L4, scaffolded) appends each day into the **published virtual Icechunk
store** on source.coop (`e4drr-project/forecasts/ecmwf_ifs_ens_aws_s3_icechunk_vd`); see §9.

## 2. Architecture — two engines

| Role | Tool | Responsibility |
|---|---|---|
| **Foreman** | ecFlow | Fires the 07:00 cron, sequences the stages, retries, records status |
| **Worker** | lithops | Fans the 51 members out to **Google Cloud Run** and writes GCS |

ecFlow runs in a **container** (isolated: no lithops, no cloud creds); the actual pipeline
runs on the **host**. They are bridged by a small **host executor** — an ecFlow task
`curl`s a whitelisted HTTP endpoint on the host, which runs the real command in the host
venv and returns the exit code as HTTP status.

```
ecFlow container ── curl ──▶ host executor (:8091) ── run ──▶ lithops ──▶ Cloud Run ──▶ GCS
      │                                                                                  ▲
      └── 07:00 cron → L1 discover → L2 lithops_parquet → L3 icechunk → L4 publish ──────┘
                         (each stage triggers the next on `complete`)
Dashboard (:8090) ── reads ecFlow log + REST ──▶ run history, per-run logs, live status
```

## 3. The four stages (L1–L4)

| Stage | ecFlow task | What it does | Status |
|---|---|---|---|
| **L1** | `discover` | Read-only preflight: GCS store reachable + S3 `00z` run available for the date | live |
| **L2** | `lithops_parquet` | The real work — era-aware Cloud Run run producing 51 parquet, verified 51/51 in GCS | live |
| **L3** | `icechunk_append` | Append the date into the virtual Icechunk store (append along `time`) | **scaffold** |
| **L4** | `publish_mirror` | Mirror/publish to source.coop | **stub** |

Tasks are chained by triggers (`trigger discover == complete`, etc.), so the chain flows
on its own. The **cron is on the `day` family**, so the whole family re-queues and runs
once per day.

## 4. Era handling (49r1 / 50r1) — the daily correctness guard

ECMWF changed its IFS schema at the `49r1 → 50r1` cutover (2026-05-13): the control member
moved from the `enfo` stream to `oper`, and levels/vars changed. Era selection is **two
switches that must agree**:

| Switch | Where | Controls |
|---|---|---|
| 1 — `ECMWF_CONTROL_STREAM` / `ECMWF_REFERENCE_DATE` | env (`era_profiles/<era>.env`) | which S3 bytes are read |
| 2 — runtime image tag | `lithops_config.<era>.yaml` | which template decodes them |

If they disagree, the run silently writes **zero files**. The guard is
**`run_era_daily.sh <era> <YYYYMMDD> [run]`** (in the operating repo, `cno-e4drr`):

- asserts switch 1 and switch 2 agree, and that the date belongs to the era — else hard-exit;
- treats the driver's exit-124 (hang-at-exit) as success;
- **verifies 51/51 objects in GCS** — never trusts the exit code.

The executor picks the era from the date and calls this wrapper, so the daily run is always
era-correct. (Dates ≥ 2026-05-13 are `50r1`: `oper` / ref `20260513`.)

## 5. Scheduling & self-healing

The workflow is designed to keep running with **no babysitting**:

| Concern | Mechanism |
|---|---|
| Daily trigger | `cron 07:00` on the `day` family (07:00, not 06:00, for margin over ECMWF's ~06:00–08:00 dissemination) |
| Dashboard / executor crash | systemd `Restart=always` |
| ecFlow container crash / host reboot | Docker `restart: unless-stopped` |
| State across restart | ecFlow checkpoints every 120 s; the entrypoint **restores from checkpoint** |
| **Server comes back RUNNING** (not HALTED) after a restart | the entrypoint waits for the server, then `--restart`s it — so scheduling never stays paused |
| A day aborts | the cron re-queues the family fresh next day |

## 6. Where everything lives

| What | Location |
|---|---|
| Output data | GCS `gs://gik-ecmwf-aws-tf/v20260623_run_par_ecmwf/YYYY/MM/DD/00z/*.parquet` |
| Compute | Cloud Run, project `e4drr-crafd`, `europe-west3`, image `…/ecmwf-lithops-runtime:50r1` |
| Generic engine + dashboard + pyflow (this repo) | `icpac-igad/ecflow @ deployment` → [`deployment/`](deployment/) |
| Project-specific suite + pipeline + era files | `icpac-igad/cno-e4drr` → `devops/…` |
| On the server (`crafd-gpu`) | ecFlow state/logs `~/e4drr-ecflow/data/`; dashboard+executor `~/e4drr-ecflow-dashboard/`; pipeline `~/cno-e4drr/devops/lithops_cr_ecmwf_gik/` |
| Future Icechunk store | source.coop `e4drr-project/forecasts/ecmwf_ifs_ens_aws_s3_icechunk_vd` (group `50r1/00z`) |

The [`deployment/`](deployment/) layout:

```
docker/            engine stack — docker-compose(.crafd).yml, Makefile, images/ecflow (Dockerfile + entrypoint)
dashboard/         Prefect-style monitoring UI + host-executor bridge + systemd templates
pyflow/            config-driven Python-API suite generator (a new pipeline = a new YAML)
suites/include/    generic head.h / tail.h job includes
```

## 7. How to use it

The daily run is automatic. These are the manual operations. On the server, from
`~/e4drr-ecflow`, `make` wraps `ecflow_client`; or call it directly:

```bash
DK="docker exec e4drr-ecflow-server ecflow_client --host=localhost --port=3141"

# status of the whole suite
$DK --get_state /ecmwf_ifs_gik

# run a specific date NOW (e.g. backfill) — set the date, reset, start the chain
$DK --alter=change variable RUN_DATE 20260824 /ecmwf_ifs_gik/day
$DK --force=queued recursive /ecmwf_ifs_gik
$DK --run /ecmwf_ifs_gik/day/discover
# (then clear it again so the cron uses each day's date)
$DK --alter=change variable RUN_DATE "" /ecmwf_ifs_gik/day

# pause / resume the daily automation
$DK --suspend /ecmwf_ifs_gik      # stops the cron from firing
$DK --resume  /ecmwf_ifs_gik      # re-arm (must be resumed for daily runs!)
```

**Backfill several dates:** loop the block above over each date, or use the pipeline's
`run_backfill_00z.sh` in `cno-e4drr` directly (bypasses ecFlow).

## 8. Monitoring — the dashboard

A dependency-free, Prefect-style UI served from the host (no tunnels), over Tailscale or
the LAN:

```
http://<tailscale-ip>:8090        # e.g. http://100.65.116.127:8090
http://<lan-ip>:8090              # on the ICPAC LAN
```

- **Runs** — every run, filterable (Today / This week / This month); click a run for its
  single continuous log. **Run history and logs persist permanently** (a per-run index +
  archived logs), independent of the ecFlow log's rolling window.
- **Secrets are redacted** — `ECF_PASS`, keys, tokens, etc. are scrubbed from logs on
  archive and on serve.
- The server **fails loud** at startup if its log/job paths are misconfigured (so it can't
  silently show "no runs").

## 9. L3/L4 — the Icechunk store (scaffolded, not yet live)

L3 appends each day into the published virtual Icechunk store on source.coop. The append
plumbing (`icechunk_append.py`, `--selftest`) is built and tested; what remains is the
**transform** from the L2 kerchunk parquet refs to a `gribberish`-coded virtual dataset,
plus source.coop write credentials. The scaffold **never writes the live store** without
an explicit flag. See `cno-e4drr` for `icechunk_append.py`.

## 10. Deploy / rebuild

```bash
cd ~/e4drr-ecflow
make up-crafd                       # start engine + REST proxy on crafd-gpu (Tailscale + LAN)

# rebuild the engine image after an entrypoint/Dockerfile change, then recreate:
docker build -t e4drr/ecflow:5.18.0 --build-arg ECFLOW_VERSION=5.18.0 images/ecflow/
make up-crafd                       # recreates with the new image; entrypoint auto-resumes to RUNNING
```

Config comes from `.env` (copy `.env.example`; **secrets are never committed**). The
dashboard and executor run as systemd user services (see `deployment/dashboard/systemd/*.example`);
the real host-wired units live in the private `cno-e4drr` deploy overlay.

## 11. Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Daily run doesn't fire | Suite **suspended**, or no `cron` on the family | `--resume`; ensure `cron 07:00` is in the def |
| Run writes **0 files** | Era mismatch (switch 1 ≠ switch 2) | `run_era_daily.sh` guards this; check `era_profiles` vs `lithops_config.<era>.yaml` |
| Dashboard shows **no runs** | `ECF_DATA_DIR` not set in the unit → reads a placeholder log path | set `ECF_DATA_DIR` + `GIK_SUITE` in the dashboard unit (startup now warns loudly) |
| `discover` aborts immediately | Executor unit missing `GIK_PIPE_DIR` / `GIK_VENV_PY` / `GIK_SA_KEY` | set them in `gik-executor.service` |
| A finished run shows **"running"** | suite-complete line scrolled out of the parse window | handled — states self-finalize once the last stage completes |
| Server **HALTED** after a restart | (old entrypoint) | fixed — the entrypoint auto-`--restart`s to RUNNING |
| Off-site users can't reach it | ICPAC firewall blocks outbound **UDP**, so Tailscale is relay-only and flaps | on-prem/LAN is fine; for reliable remote, open outbound UDP (3478 + 41641) for the host |

---

## About ecFlow (upstream)

*ecFlow* is a client/server workflow package that enables users to run a large number of
programs (with dependencies on each other and on time) in a controlled environment. It
provides tolerance for hardware and software failures, combined with restart capabilities.
It is used at ECMWF to run all their operational suites. Upstream docs:
https://ecflow.readthedocs.io/.

### Copyright and licence

Copyright 2005- European Centre for Medium-Range Weather Forecasts (ECMWF).

This software is licensed under the terms of the Apache Licence Version 2.0, which can be
obtained at http://www.apache.org/licenses/LICENSE-2.0. In applying this licence, ECMWF
does not waive the privileges and immunities granted to it by virtue of its status as an
intergovernmental organisation nor does it submit to any jurisdiction.
