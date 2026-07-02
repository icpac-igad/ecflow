# Deliverable B — REST API Gap Analysis for a Web UI

**What a browser front-end still needs from the backend: the ecFlow `/v1` REST API compared against what the desktop `ecflowUI` does via the native `ClientInvoker` protocol.**

- Repo: `/scratch/notebook/ecflow`, branch `develop`, HEAD `094fa1a72`.
- Method: enumerated the REST routes and their handlers (`libs/rest/src/ecflow/http/ApiV1.cpp`, `ApiV1Impl.cpp`), the native client capabilities (`libs/client/src/ecflow/client/ClientInvoker.hpp`), and how the desktop UI talks to the server (`Viewer/ecflowUI/src/`). The desktop side was cross-checked with an independent full inventory of every `ecflowUI → ecflow_server` interaction (sync, commands, output/log, script/manual/why, definition, auth, discovery); findings below are consistent with it.
- Companion docs: `ecflow_vs_prefect_and_deployment.md` (§3 web-UI feasibility), `ecflow_ecosystem_strategy.md` (Phase 3).

---

## 1. Headline verdict

A **read-only monitoring web UI is achievable today** with only modest backend work — the tree, per-node state, the `/v1/suites/info` dashboard feed, attributes, script, and job output are all already exposed as JSON. A **full control/operations UI** (matching ecflowUI) is **not** achievable on the current REST surface: several important capabilities are either stubbed `not_implemented` or have no endpoint at all, and two structural features the desktop UI relies on — **incremental sync** and **log-server output streaming** — are missing from REST.

Three structural gaps dominate:

| # | Gap | Impact |
|---|---|---|
| **G1** | **No incremental sync / no server push.** REST is full-snapshot request/response; the desktop UI polls with `news_local()` ("did anything change?") then applies `sync_local()` *deltas* — default cadence ~60 s, configurable, with adaptive drift (`ServerHandler.cpp:430-525`). No push/streaming anywhere. | A web UI must poll and re-fetch full snapshots; heavy for large suites; no live push. |
| **G2** | **Output/log via a separate `logsvr` process is not in REST.** REST returns the *whole* job output (line-capped) through the main server; the desktop uses a fallback chain `cache→logsvr→local-disk→main-server`. **Directory listing has *no* main-server source at all** — only `logsvr` (`list`) or local FS. Incremental "tail" is a `logsvr`-only `delta` protocol. No server-log-tail. | No efficient/live log viewing, no file picker, no big-file handling without new backend. |
| **G3** | **Write surface is partial: 34 of 57 route registrations are `not_implemented`.** Key ops (kill, why, manual, free-dependencies, zombies, edit/preprocess, delete/order) have no endpoint. | A control UI can't reach many operator actions. |

---

## 2. The two interfaces, in one paragraph

The **desktop `ecflowUI`** talks to `ecflow_server` over the **native binary TCP protocol** via `ClientInvoker` (wrapped in `ServerHandler`/`ServerComThread`), and to a **separate `logsvr` process** for output files (`OutputFileClient`, incremental `LogServerFetchMode`). The **REST API** (`ecflow_http`) is a *stateless proxy*: each request spins up a fresh `ClientInvoker` to the server and returns JSON. So the REST layer is a **curated subset** of `ClientInvoker` — anything the UI does that REST hasn't wrapped is, by definition, a gap. This document is that diff.

---

## 3. Capability matrix

Legend: 🟢 full REST support · 🟡 partial / limited · 🔴 no REST endpoint (stub or absent).

### 3.1 Tree & state monitoring (the read path)

| Capability | Desktop mechanism | REST `/v1` | Status | Note |
|---|---|---|---|---|
| Full node tree | `sync_local()` → `Defs` | `GET /suites/tree`, `/suites{path}/tree` (`?content=basic\|full`) | 🟢 | JSON tree via `TreeGeneration.hpp` |
| Per-node state | in `Defs` | `GET /suites{path}/status`, `/suites{path}/info` | 🟢 | `/info` returns `{path,state,state_change_time}` filter/sort — ideal dashboard feed |
| Suite list | `Defs.suites()` | `GET /suites` | 🟢 | |
| Node attributes (events/meters/labels/limits/vars/times…) | in `Defs` | `GET /suites{path}/attributes` | 🟢 | ~40 `to_json` overloads |
| Server state/stats | `stats()`, server vars | `GET /server/status`, `/server/attributes`, `/statistics`, `/server/ping` | 🟢 | |
| **Incremental update (delta)** | **`news_local()` then `sync_local()` deltas** + handle registration `ch1_register` | **none** | **🔴 G1** | REST re-fetches full snapshots; no delta, no push |
| Refresh cadence | UI polls at `UpdateRate` (**default ~60 s, configurable**, adaptive drift) | client must poll | 🟡 | Works, but full-tree re-fetch is inefficient at scale |

### 3.2 Node commands (the control path)

| Command | `ClientInvoker` | REST `/v1` | Status |
|---|---|---|---|
| begin, resume, suspend, requeue | `begin/resume/suspend/requeue` | `PUT /suites{path}/status` `{action:…}` | 🟢 |
| execute / run | `run()` | `action:"execute"` | 🟢 |
| force state (queued/complete/aborted/submitted…) | `force()` | `action:"abort"/"rerun"/"complete"/…` → `force` | 🟢 |
| defstatus change | `alter change defstatus` | `action:"defstatus"` | 🟢 |
| archive / restore | `archive()/restore()` | `action:"archive"/"restore"` | 🟢 |
| **kill** (running job) | `kill()` | — | 🔴 (only kill-output is fetchable, not a kill command) |
| **free dependencies** (trigger/time/date/all) | `freeDep`/`alter` free | — | 🔴 |
| **delete node(s)** | `delete_node/_nodes/_all` | partial: `DELETE /suites{path}/definition` | 🟡 (definition-delete only) |
| **order** (reorder siblings) | `order()` | — | 🔴 |
| **requeue variants / rerun with options** | `requeue`(opts) | basic only | 🟡 |

### 3.3 Attributes create/modify/delete (the edit path)

| Capability | `ClientInvoker` | REST `/v1` | Status |
|---|---|---|---|
| Add/change/delete meter, event, label, variable, limit, cron, complete, late, aviso, mirror… | `alter add/change/delete` | `POST/PUT/DELETE /suites{path}/attributes` | 🟢 (implemented via `client->alter`) |
| Server-level variables | `alter / "/"` | `POST/PUT/DELETE /server/attributes` | 🟢 |
| Child commands (event/meter/label/queue) | child API | via attributes handler (task-context) | 🟢 |

*(Attributes are the one write area that is well covered.)*

### 3.4 Output & logs

| Capability | Desktop mechanism | REST `/v1` | Status |
|---|---|---|---|
| Read a task's job output | fallback chain `cache→logsvr→local-disk→`​`client->file(jobout)` | `GET /suites{path}/output` (`client->file "jobout"`, line-capped) | 🟡 (whole file, via main server) |
| **Incremental / tail large output** | **`OutputFileClient` `delta` fetch from `logsvr` (port ~19999)** | **none** | **🔴 G2** |
| **Output directory listing** (pick among files) | `OutputDirClient` `list` (logsvr) or local FS — **no main-server source** | **none** | **🔴 G2** (nothing to wrap server-side) |
| Server log (last N lines) | `ci_->getLog(100)` (HistoryTask, main server) | **none** | 🔴 (native RPC exists; no route) |
| Live tail of server log | none (re-fetch on timer) | **none** | 🔴 G2 |

### 3.5 Script / manual / why / zombies

| Capability | `ClientInvoker` | REST `/v1` | Status |
|---|---|---|---|
| Read task `.ecf` script | `file("script")` | `GET /suites{path}/script` | 🟢 |
| **Preprocessed job / edit-preprocess** | `edit_script_preprocess/edit/submit` | — | 🔴 |
| **"Manual"** (task documentation) | `file("manual")` | — | 🔴 |
| **"Why?"** (why is a node not running) | **client-side** — `node->bottom_up_why()` computed over the fully-synced defs, not a server RPC | — | 🔴 (web UI needs a *new* server-side why endpoint, or a full-defs download) |
| Preprocessed job file (`job`) / job-status file (`stat`) | `file("job")` / `file("stat")` | — | 🔴 |
| **Zombies** list & actions (fob/fail/adopt/kill…) | zombie API | — | 🔴 |
| **Edit history** | `edit_history()` | — | 🔴 |

### 3.6 Suite definition & deployment

| Capability | `ClientInvoker` | REST `/v1` | Status |
|---|---|---|---|
| Read node/suite definition | `get_defs`/`file` | `GET /suites{path}/definition` | 🟢 |
| Create suite | `load()` | `POST /suites` (`client->load`) | 🟢 |
| Replace/update node definition | `replace()` | `PUT /suites{path}/definition` (`client->replace`) | 🟢 |
| Delete node via definition | `delete_node` | `DELETE /suites{path}/definition` | 🟢 |
| **(Note)** for git-tracked deployment, use **tracksuite**, not REST | — | — | — (by design) |

### 3.7 Server administration

| Capability | `ClientInvoker` | REST `/v1` | Status |
|---|---|---|---|
| halt / shutdown / restart server | `halt/shutdown/restart` | `PUT /server/status` (server state update) | 🟡 (verify which transitions are allowed) |
| force checkpoint | `checkPtDefs` | — | 🔴 |
| reload whitelist / passwd | `reloadwsfile/reloadpasswdfile` | mentioned in code; no clear route | 🔴/🟡 |
| ping | `pingServer` | `GET /server/ping` | 🟢 |
| **shutdown** (of the REST proxy itself) | — | `GET /v1/shutdown` | 🟢 (stops `ecflow_http`, not the engine) |

### 3.8 Auth, security, discovery

| Capability | Desktop | REST `/v1` | Status |
|---|---|---|---|
| User / custom-passwd auth | ClientInvoker user+passwd | HTTP **Basic auth** (forwarded to server) + **bearer tokens** | 🟢 |
| SSL/TLS | optional | HTTPS by default; **SSL required for state-altering commands** | 🟢 |
| Multi-server / server list | UI server list | none (one backend per `ecflow_http`, via `ECF_HOST`/`ECF_PORT`) | 🟡 (front-end concern; run one proxy per server or add routing) |

---

## 4. Endpoint implementation status (source of truth)

From `libs/rest/src/ecflow/http/ApiV1.cpp` (routes) — **23 real handlers, 34 `not_implemented` stubs** out of 57 verb registrations:

| Resource | GET | POST | PUT | DELETE |
|---|---|---|---|---|
| `/v1/suites` | ✅ read | ✅ create | 🔴 | 🔴 |
| `/v1/suites{path}/tree` | ✅ read | 🔴 | 🔴 | 🔴 |
| `/v1/suites{path}/definition` | ✅ read | 🔴 | ✅ update | ✅ delete |
| `/v1/suites{path}/status` | ✅ read | 🔴 | ✅ update | 🔴 |
| `/v1/suites/info`, `/suites{path}/info` | ✅ read | 🔴 | 🔴 | 🔴 |
| `/v1/suites{path}/attributes` | ✅ read | ✅ create | ✅ update | ✅ delete |
| `/v1/suites{path}/script` | ✅ read | 🔴 | 🔴 | 🔴 |
| `/v1/suites{path}/output` | ✅ read | 🔴 | 🔴 | 🔴 |
| `/v1/server/ping` | ✅ read | 🔴 | 🔴 | 🔴 |
| `/v1/server/status` | ✅ read | 🔴 | ✅ update | 🔴 |
| `/v1/server/attributes` | ✅ read | ✅ create | ✅ update | ✅ delete |
| `/v1/statistics` | ✅ read | 🔴 | 🔴 | 🔴 |
| `/v1/shutdown` | ✅ (stops proxy) | 🔴 | 🔴 | 🔴 |

Capabilities present in `ClientInvoker.hpp` but with **no REST route at all**: `kill`, `why`, `manual`, free-dependencies, `zombies`, `edit_history`, `edit_script_preprocess/edit/submit`, `order`, `delete_node(s)/all` (except via definition), `check`, `plug`, `group`, `new_log`/`get_log_path` (server log), force `checkpoint`, and the **`logsvr` output streaming** path.

---

## 5. What this means for the phased plan

### 5.1 Phase 3a — Read-only monitoring UI (recommended first, low risk)
**Buildable now.** Needs only: `GET /suites/tree` + `/suites/info` (dashboard), `/status`, `/attributes`, `/script`, `/output`, `/server/*`, `/statistics`. Auth + HTTPS already present.
- **Minimal backend work:** (a) decide a polling cadence and add cheap change-detection so the SPA isn't re-pulling the whole tree — ideally a lightweight "has-anything-changed since T" endpoint (wraps `news_local()`) to close **G1** for reads; (b) confirm `/output` size limits/pagination for large files.

### 5.2 Phase 3b — Full control/operations UI (larger backend effort)
To match ecflowUI you must add REST endpoints for the 🔴 rows, in rough priority:
1. **Operator commands:** `kill`, free-dependencies, `delete`/`order`, requeue-with-options. (Wrap existing `ClientInvoker` calls — mechanically straightforward; each is a new handler replacing a `not_implemented` stub.)
2. **Output/log (G2):** an output *directory* listing endpoint, an incremental/`Range`-based output read (tail), and a server-log endpoint. This is the largest single item because the desktop path uses a separate `logsvr` process (default port ~19999) with a `delta`/`list` protocol — and crucially **directory listing has no main-server source at all**, so a REST endpoint can't just wrap `ClientInvoker`; it must either **HTTP-front the existing `logsvr`** or read the output filesystem directly. Decide that first.
3. **Diagnostics:** `why`, `manual`, `zombies` (list + fob/fail/adopt/kill), `edit_history`, `edit_script_preprocess`.
4. **Live updates (G1):** add Server-Sent Events or WebSocket (or ETag/delta polling) so the UI updates without full re-fetch.
5. **Admin:** force `checkpoint`, reload whitelist/passwd, and verify the allowed `/server/status` transitions (halt/shutdown/restart).

### 5.3 Rough effort shape
- **Phase 3a:** small — days, mostly frontend + one change-detection endpoint.
- **Phase 3b command/diagnostic endpoints:** moderate — each is a thin wrapper over an existing `ClientInvoker` method replacing a stub; the bulk is deciding request/response JSON shapes and tests.
- **Phase 3b output/log streaming (G2) + live push (G1):** the real engineering — design decisions, not just wrappers.

---

## 6. Recommendation

1. **Build Phase 3a (read-only monitoring) now** against the existing API — it delivers the "monitored by more than the team" value (companion IBF doc §6) with minimal backend change, and de-risks the frontend stack.
2. **Add one change-detection endpoint** early to avoid full-tree re-polling (partial G1) — highest value-per-effort backend item.
3. **Treat G2 (output/log streaming) as the flagship Phase 3b backend task** — scope whether to HTTP-front the existing `logsvr` or add ranged reads; it is the one item that is genuinely new engineering rather than wrapping `ClientInvoker`.
4. **Fill control/diagnostic endpoints incrementally** by replacing `not_implemented` stubs with thin `ClientInvoker` wrappers, prioritized by what operators actually use (kill, free-dep, why, zombies).
5. **Keep suite deployment out of the web UI** — that path is **tracksuite** (git-tracked), by design; the web UI is for monitoring and runtime operations, not authoring.

> Note: the REST API is officially flagged **experimental** ("subject to change", `docs/rest_api.rst`). Pin and version the contract (the `/v1` prefix helps) before committing a frontend to it, and coordinate added endpoints upstream so they aren't lost on upgrade.

---

## Appendix — key files

| Area | File |
|---|---|
| REST routes (impl vs stub) | `libs/rest/src/ecflow/http/ApiV1.cpp:665-830` |
| REST handlers (status/attrs/output/definition) | `libs/rest/src/ecflow/http/ApiV1Impl.cpp` (`update_node_status_by_user:1237`, `get_node_output:591`, attributes create/update/delete, `replace`) |
| Native client surface | `libs/client/src/ecflow/client/ClientInvoker.hpp` |
| Desktop sync model | `Viewer/ecflowUI/src/ServerComThread.cpp`, `ServerHandler.cpp` (`sync_local`/`news_local`) |
| Desktop output via logserver | `Viewer/ecflowUI/src/OutputFileClient.cpp` (`LogServerFetchMode`, delta fetch), `OutputDirClient.cpp` |
| Auth / SSL | `libs/rest/src/ecflow/http/BasicAuth.cpp`, `TokenStorage.cpp`, `HttpServer.cpp`; `docs/rest_api.rst` |
