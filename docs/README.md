# ecFlow Deployment Guide — Documentation Index & Way Forward

**A strategic overview of the ecFlow ecosystem, the forked repository, and how to deploy it for impact-based forecasting and continuous risk monitoring.**

- **Repository:** https://github.com/icpac-igad/ecflow (forked from https://github.com/ecmwf/ecflow)
- **Status:** Using the upstream ecFlow with **minimal customization**; focus is entirely on **deployment and operational integration**.
- **Deployment targets:** Local VM, cloud VM, and Cloud Run setup.
- **Date:** 2026-07-22

---

## 1. Documentation Overview & Navigation

The following markdown files guide different audiences and concerns. Start with the one that matches your role:

### For Decision-Makers & Managers
📄 **`why_workflow_management_for_ibf.md`** — *plain-language introduction*
- **Audience:** forecasters, analysts, managers.
- **Scope:** Why a workflow management system is needed for Impact-Based Forecasting (IBF) and continuous risk monitoring. The problem it solves, what it delivers, and how it transforms operational capability.
- **Key takeaway:** A WMS turns fragile personal scripts into a shared, monitored, recoverable operational service visible to the whole team and beyond.

### For Technical Architects & Operators
📄 **`ecflow_vs_prefect_and_deployment.md`** — *technical assessment + deployment topology*
- **Audience:** engineers deciding tool fit and sizing infrastructure.
- **Scope:** Why ecFlow is suited to operational forecasting workflows. Database-free verification. Sizing guidance (1 GB VM). Cloud Run vs. VM trade-offs. Detailed architectural analysis of ecFlow's stateful singleton design.
- **Key takeaway:** ecFlow is a stateful singleton — it must run always-on on a VM. The REST API (`ecflow_http`) is stateless and can scale on Cloud Run as a read/monitor tier in front of it.

### For Integration & Tool Selection
📄 **`ecflow_ecosystem_strategy.md`** — *five-tool platform view*
- **Audience:** teams building the full operational stack (authoring, version control, deployment, monitoring).
- **Scope:** How ecFlow works as an ecosystem: **pyflow** (pythonic suite authoring), **pyflow-wellies** (config-driven consistency), **tracksuite** (git-tracked deployment), **ecFlow-light** (remote task telemetry), and **ecflow_http** (web monitoring).
- **Key takeaway:** You don't trade away "it's just Python" ergonomics — pyflow + wellies give it to you; tracksuite gives you git-native operational discipline instead of a database.

### For API & Web UI Development
📄 **`rest_api_gap_analysis.md`** — *REST endpoint audit + phased UI roadmap*
- **Audience:** developers building a web UI or extending the API.
- **Scope:** What the REST API (`/v1` routes) currently exposes, what it doesn't, and the architectural gaps (incremental sync, output streaming, operator commands). Read-only monitoring UI vs. full operations UI effort estimate.
- **Key takeaway:** A read-only dashboard is buildable today. A full operations UI needs backend work; start with the gap-analysis findings to decide scope.

---

## 2. Quick-Start Deployment Scenarios

### Scenario A: Local Development (One Machine)
Run everything on a single VM or bare metal:
1. Build ecFlow from source (C++ server, Python API, REST layer).
2. Start `ecflow_server` locally with a local `ECF_HOME` (checkpoint, scripts, logs).
3. Use `ecflow_client` (CLI) or `ecflowUI` (Qt desktop) to interact.
4. Run jobs locally via shell scripts (`.ecf` templates).

**When to use:** Early prototyping, testing suite definitions locally, validating a workflow before production.

**Setup reference:** `ecflow_vs_prefect_and_deployment.md` §4 (server sizing and architecture).

---

### Scenario B: Shared Cloud VM (Team's Production)
Run a single always-on GCP/AWS VM as the operational engine, with remote task execution:
1. **VM:** small (e2-micro/e2-small, 1-2 GB RAM), persistent disk for `ECF_HOME`, always-allocated CPU (never scale to zero).
2. **Server:** `ecflow_server` daemon running 24/7 on the VM.
3. **Task execution:** configure `ECF_JOB_CMD` to submit jobs to **Cloud Run, Batch, or an HPC cluster** (not local processes).
4. **Monitoring:** `ecflow_http` (stateless REST proxy) deployed on Cloud Run to expose the live state over HTTPS/JSON.
5. **Deployment:** use **tracksuite** to stage suite definitions to the VM, git-tracked with rollback.

**When to use:** Operational forecasting and risk products where reliability, recovery, and shared visibility are critical.

**Setup reference:**
- `ecflow_vs_prefect_and_deployment.md` §4.7 (the recommended topology).
- `ecflow_ecosystem_strategy.md` §5–§6 (full five-tool platform, phased way forward).

---

### Scenario C: Cloud Run (Fully Managed, Single Instance)
Run `ecflow_server` on Cloud Run with a persistent volume (not truly stateless, but managed):
1. **Server:** `ecflow_server` as a **pinned Cloud Run instance** (`min-instances=1`, `max-instances=1`, always-allocated CPU, no scale-to-zero).
2. **Persistent storage:** Cloud Run volume for `ECF_HOME`, or NFS/Filestore mount.
3. **Monitoring tier:** separate `ecflow_http` Cloud Run service (stateless, scales horizontally).
4. **Job execution:** via `ECF_JOB_CMD` → Cloud Batch or another Cloud Run job service.

**When to use:** You prefer managed infrastructure over owning a VM, and can accept the operational constraints of a single always-on instance.

**Setup reference:** `ecflow_vs_prefect_and_deployment.md` §4.4 & §4.7 (why this works and its trade-offs).

---

## 3. Current Repository Status & Minimal Customization

The fork at `https://github.com/icpac-igad/ecflow` is **upstream ecFlow with no breaking changes**. The focus is **deployment and integration**, not code modification.

### What We Keep
- The full C++ server and client libraries (no modifications).
- The Python API and REST layer (no modifications).
- The build system and test suite (minimal changes only).
- All upstream documentation and examples.

### What We Customize (Minimal)
- **Dockerfile & Cloud Run config** (to containerize the server, if using Scenario C).
- **Deployment scripts** (tracksuite integration, VM setup).
- **Configuration templates** (ECF_HOME layout, suite examples, `.ecf` script templates).
- **This documentation** (decision guide for ICPAC's use case).

### Staying Synchronized with Upstream
Regular rebases on `upstream/develop` keep us current with bug fixes and features. Any ICPAC-specific work should be clearly isolated (e.g., in a `deployment/` or `config/` directory) so merges remain straightforward.

---

## 4. The Way Forward: Phased Deployment

Building on §6 of `ecflow_ecosystem_strategy.md`, here is the concrete sequence tailored for ICPAC's impact-based forecasting setup:

### Phase 0 — Foundations (Author + Version)
**Goal:** Define and version the workflows; nothing deployed yet.

- [ ] Set up a **Python authoring repo** using **pyflow-wellies** (`wellies-quickstart` template).
- [ ] Define 1–2 real IBF/risk suites (e.g., daily flood forecast, heat risk monitoring) in **pyflow** with YAML config.
- [ ] Put generated suites under **tracksuite** so every deployment is git-tracked from day one.
- [ ] Commit to this fork; ensure CI validates the generated definitions.

**Deliverable:** A git repo of versioned suites, ready to deploy; nothing deployed by hand.

**Reference:** `ecflow_ecosystem_strategy.md` §6.0 (Phase 0).

---

### Phase 1 — Engine on a Pinned VM (Always-On)
**Goal:** Suites run on shared, recoverable infrastructure.

- [ ] Deploy `ecflow_server` on a small always-on cloud VM (GCP e2-micro/e2-small, ~1 GB RAM).
- [ ] Set up persistent disk for `ECF_HOME` (checkpoint, logs, scripts).
- [ ] Configure `tracksuite-deploy` to push suites to the VM.
- [ ] Test the 1-second scheduler loop; confirm cron/time attributes fire on schedule.
- [ ] Set up **checkpointing** and **log pruning** (defaults are safe; see sizing guidance in `ecflow_vs_prefect_and_deployment.md` §4.6).

**Deliverable:** Suites running on shared, always-on infrastructure on schedule. Recoverable via checkpoint.

**Reference:** `ecflow_vs_prefect_and_deployment.md` §4.6–§4.7 (VM sizing and recommended topology).

---

### Phase 2 — Compute on Cloud Run + Telemetry via ecFlow-light
**Goal:** Tasks scale elastically; progress shows in the monitor.

- [ ] Configure `ECF_JOB_CMD` to submit jobs to **Cloud Run** (or Cloud Batch) instead of local fork.
- [ ] Instrument container tasks with **ecFlow-light** (UDP meter/label/event) so progress reports to the server.
- [ ] Test task output and logs (initial path: via main server; refine in Phase 3b if needed).
- [ ] **Deliverable A (Cloud Run deploy files):** Dockerfiles + Cloud Run YAML for (i) the pinned `ecflow_server` VM/service and (ii) the stateless `ecflow_http` proxy; sample task container.

**Deliverable:** Elastic cloud compute with live telemetry. Operational backbone complete.

**Reference:** `ecflow_ecosystem_strategy.md` §6.2 (Phase 2) and §5.1–§5.2 (ecFlow-light & tracksuite role).

---

### Phase 3 — Web Monitoring for the Team & Partners
**Goal:** Status visible to everyone; read-only monitoring for duty officers and management.

- [ ] **Phase 3a (this sprint):**
  - [ ] Deploy `ecflow_http` (stateless REST proxy) on Cloud Run in front of the VM.
  - [ ] Build a minimal browser SPA (tree + status dashboard) against the `/v1` REST API.
  - [ ] Scope: read-only monitoring, not operations (no kill/requeue/etc. in phase 3a).
  - [ ] Test with real suites; confirm latency and polling cadence are acceptable.

- [ ] **Phase 3b (future, if needed):**
  - [ ] **Deliverable B (REST API gap analysis):** Scope what operations endpoints are missing (kill, free-dependencies, zombies, why, etc.). Decide priority.
  - [ ] Add operator commands to the REST API to match ecflowUI capabilities.
  - [ ] Improve output/log viewing (streaming, directory listing, tail).
  - [ ] Add live-update mechanism (SSE, WebSocket, or ETag/delta polling) to close the full-snapshot-polling gap.

**Recommended order:** Phase 3a (read-only SPA) first — delivers immediate value with minimal backend changes. Phase 3b if operations (interactive control) through the web is required.

**Deliverable (Phase 3a):** A live browser UI showing suite/family/task tree, state, attributes, script, and job output. Duty officers and partners can see status without touching the CLI.

**Reference:** `rest_api_gap_analysis.md` §5 (phased effort, gap analysis, and recommendations).

---

## 5. Repository Structure & Key Locations

After setup, the fork will include:

```
ecflow/
├── README.md                           # upstream ecFlow readme (unchanged)
├── docs/
│   ├── DEPLOYMENT_GUIDE.md            # This file — strategic overview
│   ├── why_workflow_management_for_ibf.md
│   ├── ecflow_vs_prefect_and_deployment.md
│   ├── ecflow_ecosystem_strategy.md
│   ├── rest_api_gap_analysis.md
│   └── [upstream docs…]
├── deployment/                        # New: ICPAC-specific deployment config
│   ├── docker/
│   │   ├── Dockerfile.server          # ecflow_server container
│   │   ├── Dockerfile.http            # ecflow_http proxy container
│   │   └── Dockerfile.taskbase        # sample task container w/ ecFlow-light
│   ├── cloud-run/
│   │   ├── deploy-server.yaml         # Cloud Run config for pinned server instance
│   │   ├── deploy-http.yaml           # Cloud Run config for stateless proxy
│   │   └── deploy-task.yaml           # Cloud Run config for sample task
│   ├── gce/
│   │   ├── vm-startup.sh              # script to set up VM on boot
│   │   └── terraform/                 # (optional) IaC for VM + disks
│   ├── tracksuite-config.yaml         # tracksuite deploy config
│   └── README.md                       # instructions for each scenario
├── suites/                            # New: example suite definitions (pyflow + YAML)
│   ├── example_flood_ibf.py           # pyflow suite definition
│   ├── config.yaml                    # wellies config (environments)
│   └── scripts/                       # .ecf task templates
├── [upstream src, libs, CMake…]
└── […rest of upstream ecflow…]
```

---

## 6. Decision Tree — Which Scenario Fits You?

```
Is this for local development & testing?
  → Scenario A (Local VM)
     Reference: ecflow_vs_prefect_and_deployment.md §4

Is this for operational forecasting / risk products?
  → Do you want to operate a VM yourself?
    → Yes
      → Scenario B (Cloud VM + Cloud Run monitoring tier)
         Reference: ecflow_vs_prefect_and_deployment.md §4.7
                    ecflow_ecosystem_strategy.md §6
    → No
      → Scenario C (Cloud Run for server + persistent volume)
         Reference: ecflow_vs_prefect_and_deployment.md §4.4 & §4.7
         (Trade-off: managed infra, but less flexible recovery)
```

---

## 7. Next Steps & Key Contacts

### Immediate Actions (Phase 0–1)
1. **Review** this guide and `ecflow_ecosystem_strategy.md` (30 min) to align on the five-tool platform.
2. **Assess** your suite definitions: use `why_workflow_management_for_ibf.md` (§5) to map your IBF chain as a suite/family/task tree.
3. **Set up Phase 0:** clone the fork, create a `suites/` directory, start a pyflow-wellies suite, commit to git.
4. **Set up Phase 1:** provision a small cloud VM, build ecFlow from source, start `ecflow_server`, test tracksuite deploy.

### Backend & Monitoring (Phase 2–3)
5. **Configure Cloud Run jobs:** set `ECF_JOB_CMD` to submit tasks to Cloud Run; instrument with ecFlow-light UDP.
6. **Deploy REST tier:** run `ecflow_http` on Cloud Run in front of the VM.
7. **Build the web SPA:** start with read-only monitoring (`rest_api_gap_analysis.md` §5.1); add operations commands later if needed.

### Ongoing
- **Rebase on upstream** regularly to keep current with bug fixes.
- **Document ICPAC-specific configs** in `deployment/README.md` so new team members can onboard.
- **Test recovery:** periodically halt the server, corrupt the checkpoint, verify restart/recovery behavior.

---

## 8. Key References & Links

| Resource | Link | Purpose |
|----------|------|---------|
| **Upstream ecFlow** | https://github.com/ecmwf/ecflow | source of truth; bug fixes, releases |
| **This fork (ICPAC)** | https://github.com/icpac-igad/ecflow | deployment & integration configs |
| **ecFlow docs** | https://ecflow.readthedocs.io | reference manual, Python API, REST |
| **pyflow** | https://github.com/ecmwf/pyflow | suite authoring DSL |
| **pyflow-wellies** | https://github.com/ecmwf/pyflow-wellies | config-driven suite scaffolding |
| **tracksuite** | https://github.com/ecmwf/tracksuite | git-tracked deployment & version control |
| **ecFlow-light** | https://github.com/ecmwf/ecflow-light | task-side UDP telemetry |

---

## 9. FAQ

**Q: Do we need to modify ecFlow code?**
A: No, not for the initial deployment. We use the upstream engine as-is. Customization is limited to deployment config (Docker, Cloud Run YAML) and suite definitions (pyflow + YAML). If you find a bug in ecFlow itself, contribute a fix upstream and rebase the fork.

**Q: What database does ecFlow use?**
A: None. State lives in RAM and is checkpointed to a flat file (`ecf.check`). This is verified in `ecflow_vs_prefect_and_deployment.md` §5. No Postgres, no Redis — operational simplicity.

**Q: Can we run multiple copies of the server for high availability?**
A: No. ecFlow is a stateful singleton by design. For HA, run a single server on a VM with a persistent disk and a standby replica that can mount and recover from the same checkpoint. (The stateless REST layer can scale horizontally in front of it.)

**Q: Can we run everything on Cloud Run?**
A: Partially. The REST proxy (`ecflow_http`) runs well on Cloud Run and scales. The server (`ecflow_server`) can run as a single pinned Cloud Run instance, but that's "managed VM, not stateless microservice." A traditional VM is simpler for the engine.

**Q: How do we handle the 1-second scheduler loop on Cloud Run?**
A: You can't — if the container is scaled to zero or suspended, the clock stops. The server must run with `min-instances=1`, `max-instances=1`, and **always-allocated CPU** to keep the scheduler ticking. This is why we recommend a traditional VM for the engine.

**Q: Can we use Prefect instead?**
A: Prefect is a valid choice if you want a managed control plane and dynamic DAGs. But ecFlow is better for operational heterogeneous workflows (NWP/geospatial) where reliability, deterministic recovery, and a database-free footprint matter. See `ecflow_vs_prefect_and_deployment.md` §2.3 for the recommendation framing.

**Q: Do we build a web UI?**
A: Start with read-only monitoring (`rest_api_gap_analysis.md` §5.1) — the tree + status dashboard, buildable today. Add operations commands later if interactive control is needed. Keep suite authoring in Git (tracksuite), not the web UI.

---

## 10. Document Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-07-22 | — | Initial deployment guide synthesized from ecosystem strategy, technical assessment, IBF rationale, and REST API analysis. |

---

**For questions or feedback, see the main README.md or raise an issue on GitHub.**
