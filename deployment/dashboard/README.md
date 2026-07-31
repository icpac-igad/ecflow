# ecFlow monitoring dashboard (Prefect-style)

A dependency-free monitoring UI for the ecFlow server — served **from the same host**,
no tunnels. Mirrors Prefect's layout (Home / Runs / Flows / Work pools) over real ecFlow
data only. stdlib Python only; the browser makes same-origin calls.

## Components
| file | role |
|---|---|
| `dashboard.html`       | single-page UI (Home, Runs with date filters, Flows, Work pools) |
| `dashboard_server.py`  | stdlib server: serves the UI, proxies `/api/*` → `ecflow_http`, exposes `/runs` + `/runlog` (persisted per-run logs) |
| `gik_executor.py`      | container→host bridge: ecFlow task `curl`s this host executor, which runs the whitelisted stage (era-aware) |
| `systemd/`             | user services for the dashboard and the executor |

## Configuration (env vars — no hard-coded paths)
| var | default | meaning |
|---|---|---|
| `ECFLOW_HTTP` | `http://localhost:8080/v1` | ecflow_http REST base |
| `DASH_PORT` / `DASH_BIND` | `8090` / `0.0.0.0` | where the dashboard listens |
| `ECF_LOG` | server log path | ecFlow log parsed for run history |
| `GIK_SUITE` / `GIK_JOB_DIR` | `ecmwf_ifs_gik` | suite + job-output dir for archived logs |

## Run
```bash
python3 dashboard_server.py            # foreground
# or: systemctl --user enable --now ecflow-dashboard gik-executor
```

Run history is archived to `run_logs/` by a background thread, so logs persist
permanently and stay visible/filterable (today / this week / this month) regardless of
browser activity.
