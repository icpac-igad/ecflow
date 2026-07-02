# ecFlow Ecosystem — Integration Strategy and Way Forward

**How ecFlow, ecFlow-light, pyflow, pyflow-wellies, and tracksuite combine into one operational workflow platform — and how it answers the "Prefect decorator" ergonomics while staying database-free and git-versioned.**

- Companion docs: `ecflow_vs_prefect_and_deployment.md` (tool choice, DB verification, cron/timekeeper, RAM, VM+Cloud Run topology) and `why_workflow_management_for_ibf.md` (the organizational case).
- Date: 2026-07-02.

---

## 1. The concern this document answers

Prefect's appeal is ergonomic: you decorate a Python function with `@flow`/`@task`, and scheduling + orchestration are woven directly into the code you already write. That gives a **single, explicit, code-defined run** — attractive for consistency and developer speed.

The worry is that ecFlow, by contrast, looks like a heavy C++ server with a separate suite-definition language, i.e. that you lose the "it's just Python" ergonomics.

**That worry is unfounded** — because ecFlow is not one tool, it is an *ecosystem*. The Python authoring ergonomics, the git version control, the config-driven consistency, and the distributed task telemetry that you might expect to give up are each provided by a dedicated companion project. This document shows how the five tools compose, maps them onto the deployment topology from the companion doc, and lays out a phased way forward — including the Cloud Run / web-UI / REST decisions left open earlier.

---

## 2. The five tools at a glance

| Tool | Role in one line | Language | Maturity | GitHub |
|---|---|---|---|---|
| **ecFlow** | The client/server **engine**: schedules, orders, runs, recovers, and monitors the workflow (the stateful singleton + clock). | C++ (+ Python API, REST, UI) | Graduated | https://github.com/ecmwf/ecflow |
| **pyflow** | High-level **Python DSL to *define/generate* ecFlow suites** in a modular, "pythonic" way. | Python | Graduated | https://github.com/ecmwf/pyflow |
| **pyflow-wellies** | **Best-practice scaffolding on top of pyflow**: YAML-config-driven suites, a `wellies-quickstart` template, and integrated git deployment. | Python | Incubating | https://github.com/ecmwf/pyflow-wellies |
| **tracksuite** | **Git version control + safe staged deployment** of suites to the server (CLI + Python API). | Python | Incubating | https://github.com/ecmwf/tracksuite |
| **ecFlow-light** | **Lightweight task-side telemetry** (update meter/label/event) sent over **UDP** to the server — for remote/containerized tasks that shouldn't be full clients. | C/C++ (task library) | Graduated | https://github.com/ecmwf/ecflow-light |

Docs: ecFlow → https://ecflow.readthedocs.io · pyflow → https://pyflow-workflow-generator.readthedocs.io · pyflow-wellies → https://pyflow-wellies.readthedocs.io

---

## 3. How they fit together — the lifecycle

The five tools are not alternatives; each owns one stage of a single lifecycle:

```
   AUTHOR                VERSION & DEPLOY          RUN                 REPORT              MONITOR
 ┌──────────┐          ┌─────────────────┐    ┌─────────────┐      ┌────────────┐     ┌──────────────┐
 │ pyflow    │  .def   │ tracksuite       │    │ ecflow_server│ UDP  │ ecflow-light│     │ ecflow_http   │
 │ + wellies │ ──────▶ │ (git diff/stage/ │──▶ │ (VM, pinned; │◀─────│ (task-side  │     │ REST + web UI │
 │ (Python + │  suite  │  deploy to host) │    │ scheduler +  │      │  meter/label│     │ (Cloud Run)   │
 │  YAML)    │  defn   │  git history     │    │  checkpoint) │      │  /event)    │     │  read by all  │
 └──────────┘          └─────────────────┘    └──────┬──────┘      └────────────┘     └──────────────┘
      ▲                        ▲                       │ ECF_JOB_CMD
      │ code review, CI        │ audit trail           ▼ (launch)
      │                        │                 ┌─────────────┐
   Git repo of suites ─────────┘                 │ Cloud Run    │  the actual compute
                                                 │ jobs / HPC   │  (hazard, exposure,
                                                 │ / batch      │   impact steps)
                                                 └─────────────┘
```

1. **Author** with **pyflow** (+ **wellies**): describe the suite as Python + YAML config. Output is an ecFlow suite definition (`.def`) and the task scripts.
2. **Version & deploy** with **tracksuite**: the generated suite is diffed against what is live, staged, committed to **git**, and pushed to the server host — with history and rollback.
3. **Run** on **ecflow_server**: the pinned always-on engine schedules and orders the tasks, launching each via `ECF_JOB_CMD` (to Cloud Run jobs, HPC/batch, or local).
4. **Report** with **ecFlow-light**: tasks running *away* from the server (Cloud Run containers, HPC nodes) send lightweight UDP telemetry (progress meters, labels, events) back to the server.
5. **Monitor** with **ecflow_http** + a web UI: the live state is exposed over REST/JSON so the whole organization — not just the authors — can watch it.

---

## 4. Answering the "Prefect decorator" advantage directly

Prefect couples *definition* and *execution* in one decorated Python process. The ecFlow ecosystem deliberately **separates** them — and, for operational forecasting, that separation is a feature, not a regression:

| Dimension | Prefect (`@flow`/`@task`) | ecFlow + pyflow + wellies + tracksuite |
|---|---|---|
| Authoring ergonomics | Decorated Python functions | **pyflow**: pythonic DSL — `Suite`/`Family`/`Task` classes and `with` context managers (`pyflow/pyflow/nodes.py`), plus **wellies** YAML config for consistency across environments |
| Explicit, consistent runs | Yes, but definition = runtime code | **Yes, and stronger**: the suite definition is a *separate, inspectable artifact*. What will run is knowable *before* anything runs. |
| Version control of the workflow | Your Python file in git; runtime state in a DB | **tracksuite**: the deployed suite itself is git-tracked, staged, and diffable against the live server — purpose-built change control |
| State backend | Requires a database | **None** — in-memory tree + flat-file checkpoint (verified in companion doc) |
| Dynamic graphs | Strong (built at runtime) | Generated at author time by pyflow (Python loops/config build the tree); less runtime-dynamic, but fully explicit and auditable |
| Reproducibility / audit | DB history | Git history of the *exact* deployed definition + ecFlow's run/edit history |

**The key reframing:** pyflow gives you Prefect-like "it's just Python, explicit and modular" authoring, while ecFlow keeps definition and execution separate so the run is **auditable and version-controlled** (tracksuite) rather than entangled with runtime code and a database. For **operational** IBF/risk pipelines — where you must prove *exactly* what ran and roll back safely — that is the more defensible design.

pyflow example (the "explicit, pythonic" definition Prefect users want). This uses the documented pyflow API — `with pf.Suite(...)`/`pf.Family`/`pf.Task`, the `>>` trigger-sequencing operator, `pf.Cron`, and `deploy_suite()` (verified against the pyflow docs, see note below):

```python
import pyflow as pf

with pf.Suite(
    "daily_flood_ibf",
    host=pf.LocalHost("localhost"),
    files=filesdir,                 # directory holding the .ecf task templates
    home=outdir,                    # ECF_HOME for generated jobs & output
    defstatus=pf.state.suspended,
) as s:
    pf.Cron("02:00")                # run daily at 02:00 (a cron re-queues on completion)

    with pf.Family("ingest") as ingest:
        pf.Task("fetch_rainfall_forecast", script='echo fetch...')
        pf.Task("fetch_river_levels",      script='echo fetch...')

    with pf.Family("process") as process:
        hazard = pf.Task("compute_hazard", script='echo hazard...')
        impact = pf.Task("compute_impact", script='echo impact...')
        hazard >> impact            # 'impact' triggered when 'hazard' completes

    with pf.Family("publish") as publish:
        pf.Task("publish_dashboard",  script='echo publish...')

    ingest >> process >> publish    # family-level ordering (each triggers the next)

s.deploy_suite()                    # generate the ecFlow definition + scripts and deploy
```

> **API-accuracy note.** The idioms above are taken from pyflow's own documentation, not guessed: `with pf.Suite('name', host=pf.LocalHost('localhost'), files=…, home=…, defstatus=pf.state.suspended)` and `s.deploy_suite()` are from *Getting Started* (`pyflow/docs/content/introductory-course/getting-started.rst`); the `t1 >> t2` sequencing operator and `node.triggers = other` assignment are from *Flow Control* (`pyflow/docs/content/introductory-course/flow-control.ipynb`); `pf.Cron("02:00")` / `pf.Cron("30 22 * * SUN")` and the note that a cron re-queues on completion are from *Time Dependencies* (`pyflow/docs/content/introductory-course/time-dependencies.ipynb`). Full reference: https://pyflow-workflow-generator.readthedocs.io. Alternative to `>>`: `impact.triggers = hazard` (trigger on completion) or `impact.triggers = hazard.some_event`.

---

## 5. The role of each tool in the target deployment

Building on the VM + Cloud Run topology from `ecflow_vs_prefect_and_deployment.md`:

### 5.1 ecFlow-light is the piece that makes Cloud Run / distributed tasks first-class
When a task runs *inside a Cloud Run container* or on a remote HPC node, making it a full `ecflow_client` (TCP child commands back to the server) is awkward. **ecFlow-light** solves exactly this: it is a tiny task-side library that fires **UDP** telemetry — `update meter`, `update label`, `update event` — to the ecFlow **UDP server** (`ecflow_udp`, shipped in ecFlow's `libs/udp`), which relays them to `ecflow_server`. Fire-and-forget, no persistent connection, minimal dependency. This is how a scaled-out, container-based compute tier reports progress into the central monitor without being tightly coupled to the engine. **Recommended for every Cloud Run / remote task that should show live progress.**

### 5.2 tracksuite is the deployment gate
Nothing reaches the production server by hand. `tracksuite-init` sets up the remote git-tracked suite folder; `tracksuite-deploy` stages the newly generated suite, shows the diff against what is live, commits to git (with an optional backup repo), and pushes to the host. This gives multi-user safety, an audit trail, and rollback — the operational discipline that raw `cron` + scp never had.

### 5.3 wellies is the consistency layer
As the number of suites and teams grows, **wellies** keeps them uniform: YAML-driven configuration (so the same suite runs across dev/test/ops by swapping config), a quickstart template so a new product isn't a blank page, and built-in tracksuite integration. This is what turns "many individuals' pyflow scripts" into a **consistent, published catalogue** of suites (the §4 "Stage 4/5" of the organizational doc).

---

## 6. Recommended way forward (phased)

A concrete sequence that also resolves the three options left open earlier (Cloud Run deploy files / web-UI prototype / REST gap analysis):

### Phase 0 — Foundations (author + version)
- Stand up a Python authoring repo using **pyflow-wellies** (`wellies-quickstart`). Define 1–2 real IBF/risk suites in **pyflow** with YAML config.
- Put the generated suites under **tracksuite** so every deployment is git-tracked from day one.
- *Deliverable:* a git repo of versioned suites; nothing deployed by hand.

### Phase 1 — Engine on a pinned VM
- Deploy **ecflow_server** on a small always-on VM (≈1 GB RAM for a modest suite; see companion §4.6) with a persistent disk for `ECF_HOME`/checkpoint/log.
- Wire `tracksuite-deploy` to push suites to it.
- *Deliverable:* suites running on shared, recoverable infrastructure on schedule.

### Phase 2 — Compute on Cloud Run + telemetry via ecFlow-light
- Point `ECF_JOB_CMD` at **Cloud Run jobs** so tasks scale elastically off the small VM.
- Instrument container tasks with **ecFlow-light** (UDP meter/label/event) so progress shows in the monitor.
- **→ Deliverable A (Cloud Run deploy files):** Dockerfile(s) + Cloud Run YAML for (i) the pinned `ecflow_server` VM/service and (ii) the stateless `ecflow_http` proxy, plus the `ecflow_udp` endpoint for telemetry.

### Phase 3 — Web monitoring for "more than the team"
- Deploy **ecflow_http** (stateless) on Cloud Run in front of the VM as the HTTPS/API tier.
- **→ Deliverable B (REST API gap analysis):** diff what `ecflowUI` does via `ClientInvoker` against what `/v1` exposes, to scope exactly what a browser UI still needs from the backend. *Do this before building the UI — it is cheap and de-risks Phase 3.*
- **→ Deliverable C (web UI prototype):** a minimal browser SPA (tree + `/v1/suites/info` status dashboard) against the REST API, for read-only monitoring by duty officers, management, and partners.

**Recommended order of the three deliverables:** **B (gap analysis) → A (Cloud Run files) → C (web UI)**. B is low-cost and tells you whether C needs backend work first; A is needed to run anything in the cloud; C is the visible payoff and should be built on the validated contract from B.

---

## 7. Summary

- **You do not trade away Prefect's ergonomics.** **pyflow** (+ **wellies**) gives explicit, modular, "just Python" suite authoring; the definition is a *separate, versionable artifact* rather than runtime code entangled with a database.
- **You gain git-native operational discipline** via **tracksuite** — staged, diffable, rollback-able deployments with an audit trail.
- **You keep the database-free, self-recovering engine** (**ecFlow**) as the always-on timekeeper on a small VM.
- **You get elastic cloud compute with live monitoring** by launching tasks on **Cloud Run** and reporting progress via **ecFlow-light** (UDP), all watched through **ecflow_http** + a web UI.
- **Net:** an integrated, ECMWF-proven, five-tool platform — Python-authored, git-versioned, database-free, cloud-scalable, and organization-wide observable — that meets the operational bar of impact-based forecasting and continuous risk monitoring better than a decorator-and-database stack.

### Repository quick links
- ecFlow — https://github.com/ecmwf/ecflow
- ecFlow-light — https://github.com/ecmwf/ecflow-light
- pyflow — https://github.com/ecmwf/pyflow
- pyflow-wellies — https://github.com/ecmwf/pyflow-wellies
- tracksuite — https://github.com/ecmwf/tracksuite
