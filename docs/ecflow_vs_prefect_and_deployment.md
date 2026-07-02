# ecFlow vs. Prefect, Web-UI Feasibility, and Cloud Run Deployment

**A technical assessment**

- Repository analysed: `/scratch/notebook/ecflow` (branch `develop`, HEAD `094fa1a72`)
- Date: 2026-07-02
- Scope: (1) why ecFlow is a sound choice against a Prefect-based stack, (2) whether the desktop GUI can become a web/HTML system, (3) whether the server can run as a stateless Cloud Run microservice, and (4) verification that ecFlow needs **no database server**.

Every claim below is backed by inspection of the source tree; file paths are given so the reasoning can be re-checked.

---

## 0. Executive summary

| Question | Verdict |
|---|---|
| Does ecFlow require an external database (Postgres/MySQL/Redis/…)? | **No.** State is held in RAM and checkpointed to a flat file. Verified — zero DB drivers in the build. |
| Does Prefect require a database? | **Yes.** Prefect Server/self-hosted requires a backing database (SQLite for dev, PostgreSQL for production). |
| Can the GUI become web/HTML-based? | **Yes, and the foundation already exists** — a JSON REST API (`ecflow_http`) ships in-tree. A new web frontend is a green-field effort, but the backend contract is done. |
| Can `ecflow_server` run as a *stateless* Cloud Run microservice? | **No — not as a horizontally-scaled stateless service.** It is a stateful singleton (in-memory tree + 1 s scheduler loop + local job execution). It **can** run as a *single* always-on Cloud Run instance with a persistent volume — a "singleton in a box", not a scale-out microservice. The `ecflow_http` REST layer, however, *is* effectively stateless and fits Cloud Run well as a front proxy. |

The single most important nuance: **"no database" is not the same as "stateless."** ecFlow avoids a database precisely because it keeps the authoritative state *in memory* — which is what makes it a stateful singleton rather than a stateless microservice. That same in-memory design also makes the running process the **clock**: cron/time attributes are evaluated against an in-RAM calendar advanced by a 1-second poll loop, so the engine must be always-on (§4.2).

**Recommended shape (matches your proposal):** run `ecflow_server` on a **small always-on VM** (≈1 GB RAM is enough for a small-to-modest suite — see §4.6) with a persistent disk, and put the stateless `ecflow_http` + web SPA on **Cloud Run** to scale the interface, connecting back to the VM (§4.7). This cleanly separates the stateful timekeeper (VM) from the stateless web tier (Cloud Run).

---

## 1. What ecFlow is

*ecFlow* is a client/server workflow scheduler that runs large numbers of interdependent programs (dependencies on each other, on time/date/cron, and on arbitrary trigger expressions) with failure tolerance and restart capability (`README.md:23`). ECMWF has run **all of its operational forecast suites on ecFlow for over a decade**; it is marked *Graduated* on ECMWF's software-maturity scale (`README.md:19-23`). That operational pedigree — a 24×7 weather-forecast production chain where a missed trigger has real cost — is the strongest single argument in its favour: it is battle-tested at exactly the kind of scale and reliability bar that matters.

### Codebase scale (from your `cloc`)

| Language | Code lines | Role |
|---|---:|---|
| C++ / C / headers | ~279,000 | server, client, node engine, REST, Python ext |
| Python | ~33,500 | Python API + tests |
| reStructuredText | ~12,100 | documentation (readthedocs) |
| SVG / Qt XML | ~70,000 | ecFlowUI desktop GUI assets |

(The 242 k "Windows Module Definition" lines are generated `.def` export files, not hand-written logic — discount them when judging effort.) The meaningful, human-authored core is a **mature ~300 k-line C++ engine with a first-class Python API and 12 k lines of docs**. This is a large, deliberately-engineered system, not a thin wrapper — which cuts both ways: enormous capability and reliability, but also a real C++ build/maintenance commitment.

### Module map (`libs/`)

```
libs/core      – primitives, serialization (Cereal), env/config
libs/attribute – node attributes (events, meters, labels, limits, times…)
libs/node      – the workflow model: Defs → Suite → Family → Task; job generation
libs/base      – command layer (client↔server request/response objects)
libs/server    – the ecflow_server daemon (scheduler, checkpoint, TCP/HTTP)
libs/client    – ClientInvoker (the C++/CLI client, `ecflow_client`)
libs/rest      – ecflow_http: JSON REST API over the client library
libs/udp       – ecflow_udp: fire-and-forget UDP child-command ingress
libs/service   – shared runtime services / registry
libs/pyext     – pybind11 Python bindings
Viewer/ecflowUI– the Qt desktop GUI (~95 k C++ LOC)
```

---

## 2. Why ecFlow over a Prefect-based system

This is a genuine trade-off, not a slam dunk. The honest framing:

### 2.1 Where ecFlow is the better fit

1. **Operational reliability track record.** A decade of unbroken ECMWF operational use on the most demanding NWP production chain in the world. Prefect (first released 2019, Prefect 2.x rewrite 2022, 3.x 2024) is younger and moves fast — API churn between major versions has been significant.

2. **No database to operate.** ecFlow's authoritative state is an in-memory tree checkpointed to a flat file (`libs/server/src/ecflow/server/CheckPtSaver.hpp`; `ecf.check` + `ecf.check.b` backup + `ecf.log`). There is **no** Postgres/MySQL/Redis to provision, tune, back up, patch, or fail over. Prefect's self-hosted server *requires* a backing database — SQLite for dev, PostgreSQL for production — plus (in typical deployments) the API server and workers. Fewer moving parts = smaller operational surface and fewer failure modes. See §5 for the verification.

3. **Deterministic, self-contained recovery.** On restart the server restores from its checkpoint and *fast-forwards* time-based attributes if downtime was < ~1 hour (`libs/server/src/ecflow/server/BaseServer.cpp:166-201`). Crash-safe atomic checkpoint writes (temp-file + rename, `CheckPtSaver::storeWithBackup`). Recovery semantics are simple to reason about because there is one authoritative process and one snapshot file.

4. **Rich native scheduling & dependency model built for HPC operations.** time/date/day/cron, trigger expressions over node state, events, meters, labels, limits (resource throttling), inlimits, repeats, late-flags, zombies handling. Job submission is pluggable via `ECF_JOB_CMD`/`ECF_KILL_CMD`/`ECF_STATUS_CMD` (`libs/server/server_environment.cfg`), so it drives batch systems (PBS/SLURM, ECMWF's `trimurti`) natively — the world it was designed for.

5. **Language-agnostic tasks.** Tasks are shell/job scripts (`.ecf`) with a header/tail and variable substitution (`libs/node/src/ecflow/node/EcfFile.cpp`). Any executable in any language is a first-class task. Prefect is Python-centric: flows and tasks are Python functions. If your workload is heterogeneous binaries and shell (typical for NWP/geospatial pipelines), ecFlow's model is a more natural fit; if your workload is Python data-engineering, Prefect's is.

6. **Lightweight footprint.** A single native daemon (`ecflow_server`), a single client binary (`ecflow_client`), optional REST (`ecflow_http`) and UDP (`ecflow_udp`) front-ends, and an optional GUI. No message broker, no result store, no DB, no orchestrator cluster required for the core to run.

### 2.2 Where Prefect is the better fit (be honest)

- **Cloud-native, elastic, Python-first data engineering.** Prefect was designed for dynamic DAGs, cloud infra, and Python-heavy analytics; it scales workers elastically and integrates with the modern data stack.
- **Managed control plane.** Prefect Cloud offloads the control plane entirely — no server for you to run.
- **Dynamic/parametric flows at runtime.** Prefect generates task graphs dynamically in Python; ecFlow suites are defined ahead of time (though the Python API can generate them programmatically).
- **Lower barrier to entry for Python teams.** `pip install prefect`, decorate a function, done. ecFlow requires building/installing a C++ server and learning its suite definition model.
- **Modern web UI out of the box.** Prefect ships a polished web UI; ecFlow's primary UI is a Qt desktop app (see §3).

### 2.3 Recommendation framing

Choose **ecFlow** when you are running an **operational production chain** of heterogeneous jobs (especially HPC/NWP/geospatial) where reliability, deterministic recovery, native time/trigger scheduling, batch-system integration, and a minimal database-free operational footprint dominate. Choose **Prefect** when you are building **Python-centric, elastic, cloud-native data pipelines** and value a managed control plane and dynamic DAGs over operational minimalism. Your context (ECMWF-lineage forecast/geospatial operations at ICPAC) points squarely at ecFlow's sweet spot.

---

## 3. Can the desktop GUI become a web/HTML system?

**Yes — and crucially, the hard part (a server-side JSON API) already exists in-tree.**

### 3.1 What exists today

**Desktop GUI — `Viewer/ecflowUI` (~95 k C++ LOC, 547 source files), built on Qt5/Qt6** (`cmake/Dependencies.cmake` searches Qt6 then Qt5; components `Widgets Gui Network Svg Core5Compat`, optional `Charts`). It talks to the server **directly over the native TCP binary protocol** via the C++ client library — `ServerHandler` / `ServerComThread` / `ServerComQueue` wrap `ClientInvoker` (`Viewer/ecflowUI/src/ServerHandler.cpp`, `ServerComThread.cpp`). Its data model (`VNode`/`VTree`/`VItem`) wraps the in-memory C++ node objects returned by the client. **This layer is not reusable from a browser** — it is Qt- and C++-bound and speaks the binary protocol, not HTTP/JSON.

**REST API — `libs/rest`, executable `ecflow_http`.** This is the enabler for a web UI. It is:

- Built on **cpp-httplib** + **nlohmann/json** (`libs/rest/CMakeLists.txt`: `httplib::httplib`, `nlohmann::json`).
- A **stateless proxy**: for each HTTP request it constructs a fresh `ClientInvoker` and forwards to `ecflow_server` over TCP (`libs/rest/src/ecflow/http/Client.cpp:103` `get_client()`), returning JSON. It holds no workflow state of its own.
- Secured with **HTTP Basic auth + tokens** (`BasicAuth.cpp`, `TokenStorage.cpp`) and **SSL/TLS** (SSL is required for any state-altering command; `docs/rest_api.rst`). Default port **8080**.
- Already documented (`docs/rest_api.rst`, flagged *experimental*).

**REST endpoints present today** (`libs/rest/src/ecflow/http/ApiV1.cpp`, each with GET/POST/PUT/DELETE as appropriate):

```
/v1/suites                              list / create suites
/v1/suites/{path}/tree                  node tree (JSON)
/v1/suites/tree                         full tree from root
/v1/suites/{path}/definition            suite definition
/v1/suites/{path}/status                node status
/v1/suites/info        /suites/{path}/info    node info (added in HEAD commit 094fa1a72)
/v1/suites/{path}/attributes            events/meters/labels/limits/vars…
/v1/suites/{path}/script                task script
/v1/suites/{path}/output                job output
/v1/server/ping | /server/status | /server/attributes
/v1/statistics
/v1/shutdown
```

The node tree and all types are serialized to JSON (`TypeToJson.cpp`, `JSON.cpp`, `TreeGeneration.hpp` — ~40 `to_json` overloads covering every attribute type). Read *and* write operations exist: state changes (requeue/suspend/…) via `PUT /status`, full attribute CRUD via `/attributes`, and definition updates via `PUT /definition`. The new `/v1/suites/info` endpoint returns a filterable/sortable JSON array of `{path, state, state_change_time}` (query params `recursive`, `type`, `state`, `sortby`, `count`) — purpose-built for a dashboard status list. **This is exactly the contract a browser SPA needs.**

### 3.2 Feasibility verdict

- **Backend: essentially ready.** A web UI would consume `ecflow_http`'s JSON REST API. The tree, status, attributes, scripts, output, and command endpoints already exist. Gaps to close: the API is marked *experimental*; you would likely want (a) an efficient incremental/streaming status feed (today it is request/response polling; consider adding SSE/WebSocket or ETag/delta polling), (b) rounding out any commands the desktop UI issues that the REST layer doesn't yet expose, and (c) a stable versioned contract before committing a frontend to it.
- **Frontend: a green-field rewrite.** None of the ~95 k lines of Qt/`VNode` code transfers to the browser; it is desktop- and binary-protocol-bound. A web frontend (React/Vue/Svelte, virtualized tree, log/output viewer, editor) is new work. The desktop UI is still useful as a **feature/UX reference spec** — replicate its tree view, info panels, log viewer, and command designer against REST equivalents.
- **Effort shape:** small-to-moderate backend hardening + a from-scratch SPA. The strategic point is that the **client/server split and a JSON API already exist**, so this is a frontend project, not a backend re-architecture.

**Bottom line:** Yes, an HTML/web GUI is realistic. Build a browser SPA against `ecflow_http`; harden and version that REST API; keep `ecflowUI` as the reference for parity.

---

## 4. Can `ecflow_server` run as a stateless Cloud Run microservice?

**Short answer: No for the *stateless, horizontally-scaled* model; a *single always-on instance* is possible but is not what "stateless microservice" means.** Your premise ("it is not using a database, therefore it can be a stateless microservice") mixes two different properties — see §0. Here is the architecture, then the fit.

### 4.1 Why it is a stateful singleton

- **Whole workflow tree lives in RAM.** The authoritative state is one in-memory `Defs` object (`defs_ptr defs_;`, `libs/server/src/ecflow/server/BaseServer.hpp:96`). There is no shared external store during operation — the checkpoint file is a *snapshot*, not a live backing store.
- **Explicit process-global singleton.** `TheOneServer::set_server(this)` (`BaseServer.cpp:56`, `libs/service/src/ecflow/service/Registry.hpp`). Job submission is also a singleton (`System`) holding a live table of forked child PIDs.
- **Always-on 1-second scheduler loop.** `NodeTreeTraverser` runs a `boost::asio` timer firing **every second** (`NodeTreeTraverser.cpp:283-289`), checked against the job-submission interval (`ECF_INTERVAL`, default 60 s). Each tick advances suite calendars, resolves time/date/cron/trigger dependencies, and generates jobs. This background scheduler must run continuously — it is not request-driven.
- **Jobs are local child processes.** `System::submit` does a real `fork()` then `execl("/bin/sh","-c", …)` running `ECF_JOB_CMD` on the server host, tracking PIDs in-process and reaping them via a `SIGCHLD` handler (`libs/node/src/ecflow/node/System.cpp:164-330`). A different/restarted container cannot reap or track jobs another container started.
- **Task call-backs demand request affinity.** Running jobs *are* clients: they call back with `--init/--complete/--abort/--event/--meter`, each mutating the same in-memory tree. Correctness requires every call to reach the *one* process that owns the tree. Two replicas → two divergent trees; there is no leader election or shared state.
- **Pervasive local filesystem coupling.** `ECF_HOME`, `ECF_FILES`, `ECF_INCLUDE` (script/include resolution, `EcfFile.cpp`), plus checkpoint/log/whitelist/passwd files (`<host>.<port>.ecf.check`, `.log`, …). Cloud Run's default filesystem is ephemeral and per-instance.

### 4.2 How cron/time scheduling works — the in-RAM singleton *is* the clock

This is the crux of why the design is what it is, so it's worth spelling out.

- **Each suite owns a `Calendar` object held in RAM** (`libs/core/src/ecflow/core/Calendar.cpp`). All time-based attributes — `time`, `today`, `date`, `day`, `cron`, and `late` — are evaluated *against that in-memory calendar*, not against the OS clock directly.
- **The 1-second poll loop advances the calendar and re-evaluates dependencies.** `NodeTreeTraverser` fires every second (`expires_after(1s)`, `NodeTreeTraverser.cpp:283-289`) and calls `update_suite_calendar_and_traverse_node_tree`. The poll period *is* the calendar increment (`CalendarUpdateParams`: "serverPollPeriod ... equivalent to calendar increment", `CalendarUpdateParams.hpp:63`). The header comment is explicit that for real-time suites "poll interval [must be] in sync with real time" (`NodeTreeTraverser.hpp:19-21`) — i.e. the running process is what keeps ecFlow's notion of time marching with the wall clock.
- **What a `cron` actually does.** On each calendar tick, `CronAttr::calendarChanged` updates its time series, and `isFree(calendar)` decides whether the current time slot is open (`CronAttr.cpp:221-236`). A cron is **"always re-queueable"** (`CronAttr.cpp:236`): after the task completes, `checkForRequeue` (`CronAttr.cpp:272`) re-queues it so it fires again at the next matching slot. So `cron 10:00` runs, completes, re-queues, and fires again the next day — the loop is driven entirely by the in-RAM calendar being advanced by the poll loop. `time`/`date`/`day` work the same way; they just aren't auto-re-queued.
- **Therefore the process is the timekeeper.** Kill `ecflow_server` and time stops advancing — there is no external scheduler and no database ticking in the background. On restart the server *fast-forwards* the calendar to the real time if downtime was under ~1 hour (`catch_up_to_real_time`, `BaseServer.cpp:166-201`); if it was down longer, missed time slots are simply missed (each attribute's `miss_next_time_slot` moves it to the next valid slot rather than firing the backlog). **This is exactly why it must be one always-on process and cannot scale to zero:** the moment the container is idle-suspended or killed, the clock stops. Cloud Run's request-driven / scale-to-zero model would silently break cron timing; an always-allocated-CPU single instance (or a plain VM) keeps the clock running.

### 4.3 Why that clashes with Cloud Run's stateless model

Cloud Run assumes containers are ephemeral, interchangeable, horizontally scalable, and may scale to zero. `ecflow_server` violates each:

1. **In-memory authoritative state** — restart loses everything since the last local checkpoint; N replicas diverge.
2. **Always-on scheduler** — a scale-to-zero / request-driven container will not reliably run the 1 s loop; missed ticks mean missed time/cron triggers.
3. **Local job execution** — jobs are children of one specific process on one specific filesystem.
4. **Request affinity** — task call-backs must hit the owning process; Cloud Run's load-balancer gives no such guarantee across instances.
5. **Ephemeral per-instance disk** — checkpoints/scripts/output need durable shared storage.

### 4.4 What you *can* deploy on Cloud Run

- **`ecflow_server` as a single pinned instance** — `min-instances=1`, `max-instances=1`, **CPU always allocated** (not request-based, so the scheduler keeps ticking), **no scale-to-zero**, session-affinity on, and a **persistent shared filesystem** mounted for `ECF_HOME`/checkpoints (Cloud Run's GCS FUSE or a Filestore/NFS mount). This works but is a "**stateful singleton in a box**": no horizontal scaling, restarts risk losing up-to-checkpoint state and orphaning in-flight jobs, and jobs execute *inside* that one container (so it must be sized for them, or configured via `ECF_JOB_CMD` to submit jobs to an external batch/compute service rather than forking locally). For a genuinely reliable operational deployment this is usually better served by a normal VM/GKE StatefulSet with a persistent disk than by Cloud Run.
- **`ecflow_http` (the REST proxy) as a real stateless Cloud Run service** — it holds no workflow state; each request opens a fresh `ClientInvoker` to the server (`Client.cpp:103`). This scales horizontally on Cloud Run and is the natural public/HTTPS entry point (and the backend for the web UI in §3), pointed at the single `ecflow_server` via `ECF_HOST`/`ECF_PORT`. **This is where Cloud Run genuinely fits.**

**To make the *engine itself* stateless/horizontal** you would have to re-architect: externalize the tree to a shared datastore, move the scheduler to a leader-elected/coordinated component, and delegate job execution to an external queue/batch system. That is a major redesign, not a packaging change.

### 4.5 Contrast with Prefect on Cloud Run

Prefect separates concerns in a way that *is* cloud-native: a stateless API server (scales horizontally) + a **database** (the durable state) + workers that pull work. On Cloud Run you would run the Prefect API/UI as a service and rely on an external Cloud SQL Postgres for state. So Prefect fits the stateless-microservice-on-Cloud-Run pattern **because** it pushes state into a database — the very thing ecFlow avoids. The two designs make opposite trade-offs:

| | ecFlow | Prefect (self-hosted) |
|---|---|---|
| Authoritative state | In-memory tree + flat-file checkpoint | External database (Postgres/SQLite) |
| Control-plane statelessness | Stateful singleton engine | Stateless API + DB + workers |
| Cloud Run fit | REST proxy yes; engine no (single pinned instance only) | API/UI yes, backed by Cloud SQL |
| Operational parts to run | 1 daemon (+optional REST/UI) | API server + DB + worker(s) (+ UI) |
| Recovery | Restore from checkpoint, fast-forward time | DB is source of truth |

Neither is "more cloud-native" in the abstract: Prefect buys horizontal statelessness at the price of always operating a database; ecFlow buys database-free operational simplicity at the price of being a singleton.

### 4.6 How much RAM does it need? Is a 1 GB always-on VM enough?

**Where the memory goes.** Because the authoritative state is the in-RAM `Defs` tree, memory scales with the *number of nodes and their attributes*, not with throughput. The consumers are:

- **The node tree itself** — every `Suite`/`Family`/`Task`/`Alias` node carries its name/path strings, state, flags, and vectors of attributes (events, meters, labels, limits, variables, times, triggers). `Node` is a heavyweight object (`libs/node/src/ecflow/node/Node.hpp`, ~267 members/containers).
- **Per-node edit history** — capped at 10 entries per node (`Defs.hpp:354 max_edit_history_size_per_node()`), so bounded.
- **Node log history** — pruned to 30 days by default (`ECF_PRUNE_NODE_LOG`); setting it to 0 keeps *all* history "at the cost [of] increasing server memory and time taken to write checkpoint file" (`docs/glossary.rst:1222`). Keep the default.
- **A transient spike during checkpoint** — saving serializes the whole tree to a temp file (`CheckPtSaver::storeWithBackup`); `CheckPt::ALWAYS` mode is explicitly warned to "cause performance issues with large Node trees" (`CheckPtSaver.hpp:65`). Budget headroom for this spike; the default `CHECK_ON_TIME` (every 120 s) keeps it periodic.

**Can it be estimated? Yes — two practical methods, since ecFlow does not publish a fixed per-node byte figure:**

1. **Checkpoint-file proxy.** The size of `ecf.check` (the serialized tree) is a good lower-bound proxy; in-RAM footprint is typically a small multiple of it (roughly ×2–4 once you add container overhead, indices, and history). Measure your real suite's `ecf.check` and multiply.
2. **Direct RSS.** Load your real suites into a test server and read the process RSS (`ps`/`/proc/<pid>/status`). This is definitive for your workload.

**Rule-of-thumb brackets** (order-of-magnitude, node = task/family/etc.):

| Suite scale | Approx. resident memory | 1 GB VM verdict |
|---|---|---|
| Small — up to ~1,000 nodes | tens of MB | **Comfortable** |
| Medium — a few thousand to ~10,000 nodes | ~100–300 MB | **Works**, but leave headroom — 2 GB is the safer floor |
| Large — tens of thousands of nodes (ECMWF-operational scale) | ~1 GB and up | Use **4 GB+** |

**So: is a 1 GB always-on VM enough?** **Yes, for a small-to-modest operational deployment** (up to roughly a couple of thousand active nodes) — an `e2-micro`/`e2-small`-class VM is fine, *provided* you (a) keep the OS footprint lean, (b) leave headroom for the checkpoint transient, and (c) keep the default log-history pruning. The engine is **CPU-light** — the 1-second loop and per-request command handling are cheap — so **RAM and a persistent disk are the real sizing levers, not CPU**. For anything past a few thousand nodes, or if you disable log pruning, step up to **2 GB**; for ECMWF-scale suites, 4 GB+. When in doubt, measure with the checkpoint-proxy method above before committing to 1 GB.

### 4.7 Your proposed topology: always-on VM + Cloud Run web tier ✅

The architecture you described — **run `ecflow_server` on a small always-on VM, and use Cloud Run to scale the web interface, connecting back to that VM** — is exactly the right split, and it maps cleanly onto how the code is layered:

```
  Browsers (HTTPS)
        │
        ▼
  ┌────────────────────────┐     stateless, scale 0..N
  │ Cloud Run: ecflow_http │     (fresh ClientInvoker per request,
  │  (+ web SPA, §3)       │      holds NO workflow state)
  └───────────┬────────────┘
              │  TCP  ECF_HOST:ECF_PORT (3141), SSL + token/basic auth
              ▼
  ┌────────────────────────┐     THE stateful singleton + clock
  │  Always-on VM (GCE)     │     min 1 GB RAM (see §4.6),
  │  ecflow_server          │     always-allocated CPU
  │  + persistent disk:     │     1-second scheduler always ticking
  │    ECF_HOME/ecf.check   │
  │    ecf.log, scripts     │
  └────────────────────────┘
```

Why this works and is the recommended shape:

- **The VM is the single source of truth *and* the timekeeper** (§4.2). It is always on, so the calendar/cron clock never stops, and its persistent disk holds `ECF_HOME`, the checkpoint (`ecf.check` + `.b`), the log, and the job scripts. This is the one component that must not scale to zero.
- **The Cloud Run tier is genuinely stateless** and can scale 0→N freely: `ecflow_http` opens a fresh `ClientInvoker` to the VM on every request (`libs/rest/src/ecflow/http/Client.cpp:103`) and keeps no workflow state, so extra instances never diverge. It is the natural home for the web SPA (§3) and public HTTPS entry point.
- **Connectivity:** prefer Cloud Run → VM over the VPC via a **Serverless VPC Access connector** to the VM's *internal* IP (keeps ecFlow's port off the public internet). Point the service at the VM with `ECF_HOST`/`ECF_PORT`. If you must expose the server publicly instead, run it with SSL and token/basic auth (recall: the REST layer *requires* SSL for any state-altering command, `docs/rest_api.rst`).
- **Job execution:** if the VM shouldn't run the jobs itself, override `ECF_JOB_CMD` so the server submits to an external batch/compute service (SLURM/PBS/Cloud Batch) rather than forking locally — keeping the VM small and stateless-of-compute.

One caveat to keep in mind: this gives you **HA on the web tier but not on the engine**. The VM is a single point of failure by design; protect it with a persistent disk (survives VM restart), frequent checkpoints, and — if you need faster recovery — a standby VM that can mount/restore the same checkpoint. That is inherent to ecFlow's singleton model, not a deployment mistake.

---

## 5. Verification: ecFlow needs NO database server ✅

**Method:** grepped the entire tree (excluding third-party & tests) for `postgres|mysql|sqlite|libpq|odbc|redis|mongodb|hiredis`, and read the build's dependency declarations.

**Result — zero database dependencies.** The only matches are non-runtime noise:
- A stray "MySQL" mention in a *comment* inside `3rdparty/cpp-httplib/include/httplib.h`.
- The words "database"/"SQL" in the **GUI's node-query feature** (`Viewer/ecflowUI/src/NodeQuery*.cpp`) and in prose docs — a search feature over the node tree, not a DBMS.
- `3rdparty/cereal` — a header-only **serialization** library, not a database.

No `find_package`/`target_link_libraries` for any DB client exists.

**Actual runtime dependencies of `ecflow_server`** (`cmake/Dependencies.cmake`, `libs/server/CMakeLists.txt`):

- **Boost** (≥1.66): `program_options`, `date_time`, `system`; header-only `asio` for timers/networking.
- **Threads** (pthreads).
- **Cereal** (bundled) — checkpoint/command serialization.
- **nlohmann/json** + **cpp-httplib** (bundled) — the REST/HTTP interface.
- **OpenSSL** (≥1.1.1, optional, `ENABLE_SSL`), **zlib** (optional, HTTP compression), **libcrypt** (password hashing).
- Optional/build-only: ecbuild, Python3+pybind11 (Python API), Qt5/Qt6 (GUI).

**What it actually needs on disk** (a writable `ECF_HOME`):
- `ecf.check` — the checkpoint (serialized defs + state).
- `ecf.check.b` — backup checkpoint.
- `ecf.log` — the log file.
- plus the suite job/include scripts and generated job/output files.

Files & defaults: `libs/core/src/ecflow/core/Ecf.cpp:29-40`, `libs/server/server_environment.cfg` (`ECF_PORT=3141`, `ECF_INTERVAL=60`, `ECF_CHECKINTERVAL=120`, `ECF_CHECKMODE=CHECK_ON_TIME`, `ECF_HOME=.`).

**Verdict:** Confirmed. ecFlow runs with **no database server** — a writable directory for its checkpoint/log/scripts is all the persistence it needs. Prefect's self-hosted server, by contrast, requires a backing database. This is a real, verified operational advantage for ecFlow — **as long as you accept the stateful-singleton design that goes with it.**

---

## 6. Recommendations

1. **Adopt ecFlow for operational job orchestration** where reliability, native time/trigger scheduling, batch integration, heterogeneous tasks, and a database-free footprint matter — its ECMWF operational lineage is directly relevant to ICPAC-style forecast/geospatial operations.
2. **Deploy the engine on a small always-on VM** (the natural home; §4.7): it is the stateful singleton *and* the cron/time clock, so it must never scale to zero. A **~1 GB VM suffices for a small-to-modest suite**; size to 2 GB beyond a few thousand nodes, 4 GB+ at ECMWF scale — RAM and a persistent disk are the sizing levers, not CPU (§4.6). Give it a persistent disk for `ECF_HOME`/checkpoint/log, and measure with the checkpoint-proxy method before committing to 1 GB. (If Cloud Run for the engine is mandated instead of a VM, it must be one always-allocated-CPU instance, min=max=1, no scale-to-zero, with a persistent volume.)
3. **Put `ecflow_http` (+ web SPA) on Cloud Run as the stateless HTTPS/API tier**, connecting to the VM via `ECF_HOST`/`ECF_PORT` (prefer a Serverless VPC connector to the VM's internal IP). This is the piece that genuinely suits Cloud Run and horizontal scaling, and it is the backend for the web UI.
4. **Build the web GUI as an SPA against `ecflow_http`**; first harden and version that REST API (add streaming/delta status, fill command gaps), using `ecflowUI` as the parity reference.
5. **Externalize job execution** via `ECF_JOB_CMD` to a batch/compute service (SLURM/PBS/Cloud Batch) so the server host isn't sized for the jobs themselves and restarts don't kill running work in-container.
6. **Correct the framing internally:** "no database" is an operational-simplicity win, *not* evidence of statelessness. The engine is a stateful singleton by design; plan the deployment around that fact.

---

### Appendix — key source references

| Concern | File(s) |
|---|---|
| In-memory tree / server singleton | `libs/server/src/ecflow/server/BaseServer.hpp:96`, `.cpp:56`; `libs/service/src/ecflow/service/Registry.hpp` |
| Checkpoint (no DB) | `libs/server/src/ecflow/server/CheckPtSaver.hpp/.cpp`; `libs/node/src/ecflow/node/Defs.cpp` (cereal); `libs/core/src/ecflow/core/Ecf.cpp:29-40` |
| 1 s scheduler loop | `libs/server/src/ecflow/server/NodeTreeTraverser.cpp:283-342` |
| Cron / time = in-RAM calendar | `libs/attribute/src/ecflow/attribute/CronAttr.cpp:221-272`; `libs/core/src/ecflow/core/Calendar.cpp`; `libs/core/src/ecflow/core/CalendarUpdateParams.hpp:63`; `BaseServer.cpp:166-201` (catch-up) |
| Memory / history / checkpoint spike | `libs/node/src/ecflow/node/Node.hpp`; `Defs.hpp:354`; `docs/glossary.rst:1222` (`ECF_PRUNE_NODE_LOG`); `CheckPtSaver.hpp:65` |
| Local job execution | `libs/node/src/ecflow/node/System.cpp:164-330` |
| Filesystem coupling | `libs/node/src/ecflow/node/EcfFile.cpp`; `libs/server/server_environment.cfg` |
| Client protocol (req/resp) | `libs/client/src/ecflow/client/ClientInvoker.cpp:430-547`; `libs/base/src/ecflow/base/ServerProtocol.hpp` |
| REST API | `libs/rest/src/ecflow/http/ApiV1.cpp`, `Client.cpp:103`, `TypeToJson.cpp`; `docs/rest_api.rst` |
| Desktop GUI ↔ server | `Viewer/ecflowUI/src/ServerHandler.cpp`, `ServerComThread.cpp` |
| Dependencies (no DB driver) | `cmake/Dependencies.cmake`; `libs/server/CMakeLists.txt`; `libs/rest/CMakeLists.txt` |
